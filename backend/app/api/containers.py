import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agentlink.commands import AgentOffline, broker
from app.agentlink.protocol import CommandResult
from app.agentlink.registry import registry
from app.db import get_db
from app.models import Container, Node
from app.schemas.container import ContainerCreate, ContainerOut
from app.security.permissions import Permission, require
from app.security.sessions import AuthContext
from app.services import audit

router = APIRouter(prefix="/containers", tags=["containers"])

ManageNodes = Annotated[AuthContext, Depends(require(Permission.NODES_MANAGE))]
MAX_ERROR_CHARS = 1024


@dataclass
class Ctx:
    db: Session
    actor_id: uuid.UUID
    ip: str
    container: Container
    node: Node


def _out(container: Container, node_name: str) -> ContainerOut:
    out = ContainerOut.model_validate(container)
    out.node_name = node_name
    return out


def _list(db: Session) -> list[ContainerOut]:
    names = dict(db.execute(select(Node.id, Node.name)).all())
    rows = db.scalars(select(Container).order_by(Container.created_at))
    return [_out(c, names.get(c.node_id, "")) for c in rows]


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _fail(outcome: str, result: CommandResult | None) -> HTTPException:
    if outcome == "offline":
        return _conflict("The agent of this node is not connected.")
    if outcome == "timeout":
        return HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, "The agent did not answer in time."
        )
    message = "The agent refused the command."
    if result is not None and result.error:
        message = result.error
    return HTTPException(422, message)


def _already_gone(error: str | None) -> bool:
    text = (error or "").lower()
    return "no such object" in text or "no such container" in text


def _audit(ctx: Ctx, action: str, outcome: str) -> None:
    c = ctx.container
    audit.record(
        ctx.db,
        action,
        actor_id=ctx.actor_id,
        target_type="container",
        target_id=str(c.id),
        ip=ctx.ip,
        details={
            "name": c.name,
            "node": ctx.node.name,
            "docker_name": c.docker_name,
            "image": c.image,
            "host_port": c.host_port,
            "outcome": outcome,
        },
    )


def _context(db: Session, container_id: uuid.UUID, actor_id: uuid.UUID, ip: str) -> Ctx:
    container = db.get(Container, container_id)
    if container is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Container not found.")
    node = db.get(Node, container.node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    return Ctx(db, actor_id, ip, container, node)


def _reserve(db: Session, body: ContainerCreate, actor_id: uuid.UUID, ip: str) -> Ctx:
    """Prüft alles, was das Panel selbst wissen kann, und reserviert den Port."""
    node = db.get(Node, body.node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    if node.status == "pending" or not registry.is_connected(node.id):
        raise _conflict("The agent of this node is not connected.")
    if not node.port_range_start <= body.host_port <= node.port_range_end:
        raise HTTPException(422, "The host port is outside the port range of this node.")
    taken = db.scalar(
        select(Container.id).where(
            Container.node_id == node.id,
            Container.host_port == body.host_port,
            Container.protocol == body.protocol,
        )
    )
    if taken is not None:
        raise _conflict("This port is already used by another container.")

    container = Container(
        node_id=node.id,
        name=body.name,
        docker_name="ew-" + uuid.uuid4().hex[:12],
        image=body.image,
        host_port=body.host_port,
        container_port=body.container_port,
        protocol=body.protocol,
        memory_mb=body.memory_mb,
        cpus=body.cpus,
        status="creating",
        created_by=actor_id,
    )
    db.add(container)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict("This port is already used by another container.") from None
    return Ctx(db, actor_id, ip, container, node)


async def _send(
    node_id: uuid.UUID, action: str, params: dict
) -> tuple[CommandResult | None, str]:
    try:
        result = await broker.send(node_id, action, params)
    except AgentOffline:
        return None, "offline"
    except TimeoutError:
        return None, "timeout"
    return result, "ok" if result.ok else "failed"


def _settle(
    ctx: Ctx, action: str, new_status: str, outcome: str, result: CommandResult | None
) -> None:
    """Schreibt das Ergebnis eines Befehls in die Datenbank und ins Audit-Log."""
    c = ctx.container
    if outcome == "ok":
        c.status = new_status
        c.last_error = None
        ctx.db.commit()
        _audit(ctx, action, outcome)
        return
    error = _fail(outcome, result)
    if action == "container.create" and outcome == "failed":
        # Der Agent hat abgelehnt, auf der Node existiert nichts.
        ctx.db.delete(c)
    else:
        c.last_error = str(error.detail)[:MAX_ERROR_CHARS]
        if action == "container.create":
            # Unklar, ob der Container existiert: Eintrag bleibt zum Aufräumen.
            c.status = "error"
    ctx.db.commit()
    _audit(ctx, action, outcome)
    raise error


def _settle_delete(ctx: Ctx, outcome: str, result: CommandResult | None) -> None:
    if outcome == "failed" and result is not None and _already_gone(result.error):
        outcome = "ok"
    if outcome not in ("ok", "forced"):
        error = _fail(outcome, result)
        ctx.container.last_error = str(error.detail)[:MAX_ERROR_CHARS]
        ctx.db.commit()
        _audit(ctx, "container.delete", outcome)
        raise error
    ctx.db.delete(ctx.container)
    ctx.db.commit()
    _audit(ctx, "container.delete", outcome)


async def _run_action(ctx: Ctx, verb: str, new_status: str) -> ContainerOut:
    if ctx.container.status == "creating":
        raise _conflict("This container is still being created.")
    action = f"container.{verb}"
    result, outcome = await _send(ctx.node.id, action, {"name": ctx.container.docker_name})
    await run_in_threadpool(_settle, ctx, action, new_status, outcome, result)
    return _out(ctx.container, ctx.node.name)


@router.get("")
def list_containers(
    _auth: ManageNodes, db: Annotated[Session, Depends(get_db)]
) -> list[ContainerOut]:
    return _list(db)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_container(
    body: ContainerCreate,
    request: Request,
    auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
) -> ContainerOut:
    ctx = await run_in_threadpool(_reserve, db, body, auth.user.id, audit.client_ip(request))
    c = ctx.container
    params = {
        "name": c.docker_name,
        "image": c.image,
        "ports": [{"host": c.host_port, "container": c.container_port, "proto": c.protocol}],
        "env": {},
        "memory_mb": c.memory_mb,
        "cpus": c.cpus,
    }
    result, outcome = await _send(ctx.node.id, "container.create", params)
    await run_in_threadpool(_settle, ctx, "container.create", "created", outcome, result)
    return _out(c, ctx.node.name)


@router.post("/{container_id}/start")
async def start_container(
    container_id: uuid.UUID,
    request: Request,
    auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
) -> ContainerOut:
    ctx = await run_in_threadpool(
        _context, db, container_id, auth.user.id, audit.client_ip(request)
    )
    return await _run_action(ctx, "start", "running")


@router.post("/{container_id}/stop")
async def stop_container(
    container_id: uuid.UUID,
    request: Request,
    auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
) -> ContainerOut:
    ctx = await run_in_threadpool(
        _context, db, container_id, auth.user.id, audit.client_ip(request)
    )
    return await _run_action(ctx, "stop", "stopped")


@router.delete("/{container_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_container(
    container_id: uuid.UUID,
    request: Request,
    auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
    *,
    force: bool = False,
) -> None:
    ctx = await run_in_threadpool(
        _context, db, container_id, auth.user.id, audit.client_ip(request)
    )
    result: CommandResult | None = None
    outcome = "forced"
    if not force:
        result, outcome = await _send(
            ctx.node.id, "container.remove", {"name": ctx.container.docker_name}
        )
    await run_in_threadpool(_settle_delete, ctx, outcome, result)
