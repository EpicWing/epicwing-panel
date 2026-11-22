import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.node import Node
from app.models.server import Server


def allocated(
    db: Session, node_id: uuid.UUID, exclude_server_id: uuid.UUID | None = None
) -> tuple[int, int]:
    """Sum of RAM and storage (MB) already assigned to servers on the node."""
    stmt = select(
        func.coalesce(func.sum(Server.memory_mb), 0),
        func.coalesce(func.sum(Server.disk_mb), 0),
    ).where(Server.node_id == node_id)
    if exclude_server_id is not None:
        stmt = stmt.where(Server.id != exclude_server_id)
    ram, disk = db.execute(stmt).one()
    return int(ram), int(disk)


def exceeds(limit: int | None, used: int, wanted: int, old: int | None) -> bool:
    """True if the requested value breaks the node's limit.

    old is None for new servers, otherwise the server's previous value.
    """
    if limit is None:
        return False
    # Unchanged values are never rejected
    if old is not None and wanted == old:
        return False
    # 0 means unlimited and would bypass the node's limit
    if wanted == 0:
        return True
    # Shrinking is always allowed, even if the node is already over its limit
    if old is not None and wanted < old:
        return False
    return used + wanted > limit


def check_fits(
    db: Session,
    node: Node,
    memory_mb: int,
    disk_mb: int,
    old_memory: int | None = None,
    old_disk: int | None = None,
    exclude_server_id: uuid.UUID | None = None,
) -> None:
    if node.ram_limit_mb is None and node.disk_limit_mb is None:
        return
    # Lock the row so two concurrent requests cannot both use up the limit
    db.execute(select(Node.id).where(Node.id == node.id).with_for_update())
    ram_used, disk_used = allocated(db, node.id, exclude_server_id)

    if exceeds(node.ram_limit_mb, ram_used, memory_mb, old_memory):
        if memory_mb == 0:
            detail = "This node has a memory limit, so the server needs a memory value above 0."
        else:
            left = max((node.ram_limit_mb or 0) - ram_used, 0)
            detail = f"Not enough memory on this node: {left} MB left of {node.ram_limit_mb} MB."
        raise HTTPException(status.HTTP_409_CONFLICT, detail)
    if exceeds(node.disk_limit_mb, disk_used, disk_mb, old_disk):
        if disk_mb == 0:
            detail = "This node has a storage limit, so the server needs a storage value above 0."
        else:
            left = max((node.disk_limit_mb or 0) - disk_used, 0)
            detail = f"Not enough storage on this node: {left} MB left of {node.disk_limit_mb} MB."
        raise HTTPException(status.HTTP_409_CONFLICT, detail)
