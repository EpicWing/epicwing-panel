import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agentlink.commands import AgentOffline, broker
from app.agentlink.registry import registry
from app.db import get_db
from app.models import Node, NodeCredential, Server
from app.schemas.node import (
    CommandOut,
    CommandRequest,
    EnrollmentOut,
    NodeCreate,
    NodeCreated,
    NodeDetail,
    NodeOut,
    NodeUpdate,
)
from app.security.permissions import AdminAuth, Permission, require
from app.security.sessions import AuthContext
from app.services import audit
from app.services import nodes as node_service

router = APIRouter(prefix="/nodes", tags=["nodes"])

ManageNodes = Annotated[AuthContext, Depends(require(Permission.NODES_MANAGE))]


def _node_out(node: Node) -> NodeOut:
    out = NodeOut.model_validate(node)
    # Online only counts with a fresh heartbeat, not by the stored value.
    out.status = node_service.display_status(node)
    return out


def _name_taken() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "A node with this name already exists.")


@router.get("")
def list_nodes(
    _auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NodeOut]:
    response.headers["X-Total-Count"] = str(db.scalar(select(func.count(Node.id))) or 0)
    nodes = db.scalars(select(Node).order_by(Node.created_at, Node.id).limit(limit).offset(offset))
    return [_node_out(n) for n in nodes]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_node(
    body: NodeCreate,
    request: Request,
    auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
) -> NodeCreated:
    if db.scalar(select(Node.id).where(func.lower(Node.name) == body.name.lower())):
        raise _name_taken()

    node = Node(
        name=body.name,
        location=body.location,
        fqdn=body.fqdn,
        port_range_start=body.port_range_start,
        port_range_end=body.port_range_end,
    )
    db.add(node)
    try:
        db.flush()
        token, enrollment = node_service.create_enrollment(db, node, auth.user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _name_taken() from None

    # The token does not go into the audit log.
    audit.record(
        db,
        "node.create",
        actor_id=auth.user.id,
        target_type="node",
        target_id=str(node.id),
        ip=audit.client_ip(request),
        details={"name": node.name},
    )
    return NodeCreated(
        node=NodeOut.model_validate(node),
        enrollment=EnrollmentOut(token=token, expires_at=enrollment.expires_at),
    )


@router.post("/{node_id}/enrollment", status_code=status.HTTP_201_CREATED)
def new_enrollment(
    node_id: uuid.UUID,
    request: Request,
    auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
) -> EnrollmentOut:
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    if node.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "This node is already registered.")

    token, enrollment = node_service.create_enrollment(db, node, auth.user.id)
    db.commit()
    audit.record(
        db,
        "node.enrollment_create",
        actor_id=auth.user.id,
        target_type="node",
        target_id=str(node.id),
        ip=audit.client_ip(request),
        details={"name": node.name},
    )
    return EnrollmentOut(token=token, expires_at=enrollment.expires_at)


def _get_node(db: Session, node_id: uuid.UUID) -> Node:
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    return node


def _detail(db: Session, node: Node) -> NodeDetail:
    credential = db.scalar(select(NodeCredential).where(NodeCredential.node_id == node.id))
    connected = node.status != "pending" and registry.is_connected(node.id)
    stats = registry.stats.get(node.id, {}) if connected else {}
    return NodeDetail(
        **_node_out(node).model_dump(),
        connected=connected,
        # Only the fingerprint, never the key itself.
        fingerprint=credential.fingerprint if credential else None,
        registered_at=credential.created_at if credential else None,
        cpu_percent=stats.get("cpu_percent"),
        ram_used_mb=stats.get("ram_used_mb"),
        disk_used_mb=stats.get("disk_used_mb"),
        history=list(registry.history.get(node.id, [])) if connected else [],
    )


@router.get("/{node_id}")
def get_node(
    node_id: uuid.UUID, _auth: ManageNodes, db: Annotated[Session, Depends(get_db)]
) -> NodeDetail:
    return _detail(db, _get_node(db, node_id))


@router.patch("/{node_id}")
def update_node(
    node_id: uuid.UUID,
    body: NodeUpdate,
    request: Request,
    auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
) -> NodeDetail:
    node = _get_node(db, node_id)
    data = body.model_dump(exclude_unset=True)

    if "name" in data and db.scalar(
        select(Node.id).where(func.lower(Node.name) == data["name"].lower(), Node.id != node.id)
    ):
        raise _name_taken()

    start = data.get("port_range_start", node.port_range_start)
    end = data.get("port_range_end", node.port_range_end)
    if start > end:
        raise HTTPException(422, "The port range is invalid: the start must not be after the end.")

    for field, value in data.items():
        setattr(node, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _name_taken() from None

    audit.record(
        db,
        "node.update",
        actor_id=auth.user.id,
        target_type="node",
        target_id=str(node.id),
        ip=audit.client_ip(request),
        details={"name": node.name, "fields": sorted(data)},
    )
    return _detail(db, node)


def _revoke(db: Session, node_id: uuid.UUID, actor_id: uuid.UUID, ip: str) -> NodeDetail:
    node = _get_node(db, node_id)
    if node.status == "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "This node has no registered agent.")
    # Without a key the agent can no longer log in. The node waits for an agent again
    # and can be set up again with a new token.
    db.execute(delete(NodeCredential).where(NodeCredential.node_id == node.id))
    node.status = "pending"
    node.last_heartbeat_at = None
    node.agent_version = None
    db.commit()
    audit.record(
        db,
        "node.revoke",
        actor_id=actor_id,
        target_type="node",
        target_id=str(node.id),
        ip=ip,
        details={"name": node.name},
    )
    return _detail(db, node)


@router.post("/{node_id}/revoke")
async def revoke_node(
    node_id: uuid.UUID,
    request: Request,
    auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
) -> NodeDetail:
    detail = await run_in_threadpool(_revoke, db, node_id, auth.user.id, audit.client_ip(request))
    await registry.disconnect(node_id)
    return detail


def _delete(db: Session, node_id: uuid.UUID, actor_id: uuid.UUID, ip: str) -> None:
    node = _get_node(db, node_id)
    if db.scalar(select(Server.id).where(Server.node_id == node.id).limit(1)) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This node still has servers. Delete them first."
        )
    name = node.name
    # Credentials and tokens are removed by ON DELETE CASCADE.
    db.delete(node)
    db.commit()
    audit.record(
        db,
        "node.delete",
        actor_id=actor_id,
        target_type="node",
        target_id=str(node_id),
        ip=ip,
        details={"name": name},
    )


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: uuid.UUID,
    request: Request,
    auth: ManageNodes,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    await run_in_threadpool(_delete, db, node_id, auth.user.id, audit.client_ip(request))
    await registry.disconnect(node_id)


def _audit_command(
    db: Session, actor_id: uuid.UUID, node: Node, body: CommandRequest, ip: str, outcome: str
) -> None:
    # Only the action and the container name, never the parameters (env can contain secrets).
    audit.record(
        db,
        "node.command",
        actor_id=actor_id,
        target_type="node",
        target_id=str(node.id),
        ip=ip,
        details={
            "name": node.name,
            "action": body.action,
            "container": body.params["name"],
            "outcome": outcome,
        },
    )


@router.post("/{node_id}/commands")
async def run_command(
    node_id: uuid.UUID,
    body: CommandRequest,
    request: Request,
    auth: AdminAuth,
    db: Annotated[Session, Depends(get_db)],
) -> CommandOut:
    node = await run_in_threadpool(_get_node, db, node_id)
    outcome = "offline"
    result = None
    if node.status != "pending" and registry.is_connected(node.id):
        try:
            result = await broker.send(node.id, body.action, body.params)
            outcome = "ok" if result.ok else "failed"
        except AgentOffline:
            outcome = "offline"
        except TimeoutError:
            outcome = "timeout"
    await run_in_threadpool(
        _audit_command, db, auth.user.id, node, body, audit.client_ip(request), outcome
    )
    if outcome == "timeout":
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "The agent did not answer in time.")
    if result is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The agent of this node is not connected.")
    return CommandOut(ok=result.ok, data=result.data, error=result.error)
