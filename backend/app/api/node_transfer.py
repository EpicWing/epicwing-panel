"""Moving a server to another node and the relay the nodes use for it."""

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api import servers as servers_api
from app.config import get_settings
from app.db import get_db
from app.models import Allocation, Node, Server
from app.models.server import ServerBackup
from app.security.server_access import ServerAccess, ServerPermission, server_access
from app.services import audit, node_transfer

router = APIRouter(tags=["node-transfer"])

DbSession = Annotated[Session, Depends(get_db)]
Transfer = Annotated[ServerAccess, Depends(server_access(ServerPermission.SETTINGS_TRANSFER))]

TRANSFER_FROM = {"offline", "error"}
MAX_TARGET_PORTS = 500
# Agents before 0.3.0 cannot download a backup from a URL.
MIN_AGENT_VERSION = (0, 3, 0)


def _agent_too_old(version: str | None) -> bool:
    """Unknown versions (for example "dev") are allowed, the node reports errors itself."""
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", version or "")
    return bool(match) and tuple(int(part) for part in match.groups()) < MIN_AGENT_VERSION


class TransferStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: uuid.UUID
    allocation_id: uuid.UUID
    # Backups that only exist on the old node cannot come along.
    delete_local_backups: bool = False


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _server(db: Session, server_id: uuid.UUID) -> Server:
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Server not found.")
    return server


def _idle() -> dict[str, Any]:
    return {"step": None, "error": None, "progress": None, "size": None, "running": False}


def _local_only(db: Session, server_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ServerBackup)
            .where(
                ServerBackup.server_id == server_id,
                ServerBackup.local.is_(True),
                or_(ServerBackup.remote_state.is_(None), ServerBackup.remote_state != "ok"),
            )
        )
        or 0
    )


@router.get("/servers/{server_id}/node-transfer")
def transfer_status(server_id: uuid.UUID, access: Transfer, db: DbSession) -> dict[str, Any]:
    server = _server(db, server_id)
    job = node_transfer.job_for(server.id)
    return {**(job.public() if job else _idle()), "local_only_backups": _local_only(db, server.id)}


@router.get("/servers/{server_id}/node-transfer/targets")
def transfer_targets(server_id: uuid.UUID, access: Transfer, db: DbSession) -> list[dict[str, Any]]:
    """The other nodes with their free ports."""
    server = _server(db, server_id)
    nodes = db.scalars(select(Node).where(Node.id != server.node_id).order_by(Node.name)).all()
    result = []
    for node in nodes:
        ports = db.scalars(
            select(Allocation)
            .where(Allocation.node_id == node.id, Allocation.server_id.is_(None))
            .order_by(Allocation.ip, Allocation.port)
            .limit(MAX_TARGET_PORTS)
        ).all()
        result.append(
            {
                "id": str(node.id),
                "name": node.name,
                "status": node.status,
                "allocations": [{"id": str(a.id), "ip": a.ip, "port": a.port} for a in ports],
            }
        )
    return result


@router.post("/servers/{server_id}/node-transfer", status_code=status.HTTP_202_ACCEPTED)
async def start_transfer(
    server_id: uuid.UUID,
    body: TransferStart,
    request: Request,
    access: Transfer,
    db: DbSession,
) -> dict[str, Any]:
    server = _server(db, server_id)
    if node_transfer.is_running(server.id):
        raise _conflict("A transfer of this server is already running.")
    if body.node_id == server.node_id:
        raise _conflict("The server already runs on this node.")
    node = db.get(Node, body.node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    allocation = db.get(Allocation, body.allocation_id)
    if allocation is None or allocation.node_id != node.id or allocation.server_id is not None:
        raise _conflict("Choose a free port on the new node.")
    for each in (db.get(Node, server.node_id), node):
        if each is not None and _agent_too_old(each.agent_version):
            raise _conflict(
                f"The agent on {each.name} is version {each.agent_version}. "
                "Update it to 0.3.0 or newer first."
            )
    if not get_settings().epicwing_public_url.strip():
        raise _conflict("Set EPICWING_PUBLIC_URL in the .env of the panel, the nodes need it.")
    busy = db.scalar(
        select(func.count())
        .select_from(ServerBackup)
        .where(
            ServerBackup.server_id == server.id,
            or_(ServerBackup.status == "running", ServerBackup.remote_state == "uploading"),
        )
    )
    if busy:
        raise _conflict("Wait until the running backup is finished.")
    if _local_only(db, server.id) and not body.delete_local_backups:
        raise _conflict(
            "This server has backups that only exist on the old node. "
            "Download them first or confirm that they may be deleted."
        )

    async with servers_api._exclusive(server.id):
        db.refresh(server)
        if server.status not in TRANSFER_FROM:
            raise _conflict("Stop the server before moving it to another node.")
        server.status = node_transfer.TRANSFER_STATUS
        server.last_error = None
        db.commit()

    job = node_transfer.Job(
        server_id=server.id,
        source_node_id=server.node_id,
        target_node_id=node.id,
        allocation_id=allocation.id,
        actor_id=access.user.id,
        delete_local_backups=body.delete_local_backups,
    )
    node_transfer.start(job)
    audit.record(
        db,
        "server.transfer_start",
        actor_id=access.user.id,
        target_type="server",
        target_id=str(server.id),
        ip=audit.client_ip(request),
        details={
            "name": server.name,
            "to_node": node.name,
            "port": f"{allocation.ip}:{allocation.port}",
        },
    )
    return job.public()


# ---------------------------------------------------------------- relay for the nodes
# The nodes have no session here. Each transfer has its own random token that is only
# valid while that transfer waits for exactly this step.


def _job(token: str) -> node_transfer.Job:
    job = node_transfer.job_by_token(token)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown transfer.")
    return job


@router.put("/node-transfers/{token}/parts/{index}")
async def upload_part(token: str, index: int, request: Request) -> Response:
    job = _job(token)
    try:
        length = int(request.headers.get("content-length", "-1"))
    except ValueError:
        length = -1
    if length < 0:
        raise HTTPException(status.HTTP_411_LENGTH_REQUIRED, "Content-Length is required.")
    try:
        etag = await node_transfer.store_part(job, index, length, request.stream())
    except node_transfer.TransferError as exc:
        raise _conflict(str(exc)) from None
    return Response(status_code=status.HTTP_200_OK, headers={"ETag": etag})


@router.get("/node-transfers/{token}/archive")
def download_archive(token: str) -> StreamingResponse:
    job = _job(token)
    if not node_transfer.archive_ready(job):
        raise _conflict("The archive is not ready.")
    return StreamingResponse(
        node_transfer.read_archive(job),
        media_type="application/octet-stream",
        headers={"Content-Length": str(job.size), "Cache-Control": "no-store"},
    )
