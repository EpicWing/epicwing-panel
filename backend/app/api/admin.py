"""Admin overview and locations. Global administrators only."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agentlink.registry import registry
from app.db import get_db
from app.models import Node, Server, User
from app.models.server import ServerBackup
from app.security.permissions import AdminAuth
from app.services import nodes as node_service

router = APIRouter(prefix="/admin", tags=["admin"])
DbSession = Annotated[Session, Depends(get_db)]


class NodeCounts(BaseModel):
    total: int
    online: int
    offline: int
    pending: int


class ServerCounts(BaseModel):
    total: int
    by_status: dict[str, int] = Field(default_factory=dict)


class UserCounts(BaseModel):
    total: int
    admins: int
    disabled: int


class BackupCounts(BaseModel):
    total: int
    running: int
    failed: int
    size_bytes: int


class NodeLoad(BaseModel):
    id: uuid.UUID
    name: str
    location: str
    status: str
    cpu_total: int | None
    ram_total_mb: int | None
    disk_total_mb: int | None
    # Live values exist only while the agent is connected.
    cpu_percent: float | None = None
    ram_used_mb: float | None = None
    disk_used_mb: float | None = None
    servers: int = 0
    ram_allocated_mb: int = 0
    disk_allocated_mb: int = 0


class Overview(BaseModel):
    nodes: NodeCounts
    servers: ServerCounts
    users: UserCounts
    backups: BackupCounts
    node_load: list[NodeLoad]


class LocationOut(BaseModel):
    name: str
    nodes: int
    online: int
    servers: int


def _servers_per_node(db: Session) -> dict[uuid.UUID, tuple[int, int, int]]:
    rows = db.execute(
        select(
            Server.node_id,
            func.count(),
            func.coalesce(func.sum(Server.memory_mb), 0),
            func.coalesce(func.sum(Server.disk_mb), 0),
        ).group_by(Server.node_id)
    ).all()
    return {node_id: (count, int(ram), int(disk)) for node_id, count, ram, disk in rows}


def _users(db: Session) -> UserCounts:
    def count(*where) -> int:
        stmt = select(func.count()).select_from(User)
        if where:
            stmt = stmt.where(*where)
        return db.scalar(stmt) or 0

    return UserCounts(
        total=count(),
        admins=count(User.is_admin.is_(True)),
        disabled=count(User.disabled_at.is_not(None)),
    )


def _backups(db: Session) -> BackupCounts:
    rows = db.execute(
        select(
            ServerBackup.status,
            func.count(),
            func.coalesce(func.sum(ServerBackup.size_bytes), 0),
        ).group_by(ServerBackup.status)
    ).all()
    by_status = {status: (count, int(size)) for status, count, size in rows}
    return BackupCounts(
        total=sum(count for count, _ in by_status.values()),
        running=by_status.get("running", (0, 0))[0],
        failed=by_status.get("failed", (0, 0))[0],
        size_bytes=by_status.get("ok", (0, 0))[1],
    )


@router.get("/overview")
def overview(_auth: AdminAuth, db: DbSession) -> Overview:
    nodes = list(db.scalars(select(Node).order_by(Node.created_at)))
    per_node = _servers_per_node(db)
    states = [node_service.display_status(node) for node in nodes]

    load = []
    for node, state in zip(nodes, states, strict=True):
        live = registry.stats.get(node.id, {}) if registry.is_connected(node.id) else {}
        count, ram, disk = per_node.get(node.id, (0, 0, 0))
        load.append(
            NodeLoad(
                id=node.id,
                name=node.name,
                location=node.location,
                status=state,
                cpu_total=node.cpu_total,
                ram_total_mb=node.ram_total_mb,
                disk_total_mb=node.disk_total_mb,
                cpu_percent=live.get("cpu_percent"),
                ram_used_mb=live.get("ram_used_mb"),
                disk_used_mb=live.get("disk_used_mb"),
                servers=count,
                ram_allocated_mb=ram,
                disk_allocated_mb=disk,
            )
        )

    by_status = {
        status: count
        for status, count in db.execute(
            select(Server.status, func.count()).group_by(Server.status)
        ).all()
    }
    return Overview(
        nodes=NodeCounts(
            total=len(nodes),
            online=states.count("online"),
            offline=states.count("offline"),
            pending=states.count("pending"),
        ),
        servers=ServerCounts(total=sum(by_status.values()), by_status=by_status),
        users=_users(db),
        backups=_backups(db),
        node_load=load,
    )


@router.get("/locations")
def locations(_auth: AdminAuth, db: DbSession) -> list[LocationOut]:
    per_node = _servers_per_node(db)
    groups: dict[str, LocationOut] = {}
    for node in db.scalars(select(Node)):
        name = node.location.strip()
        group = groups.setdefault(name, LocationOut(name=name, nodes=0, online=0, servers=0))
        group.nodes += 1
        if node_service.display_status(node) == "online":
            group.online += 1
        group.servers += per_node.get(node.id, (0, 0, 0))[0]
    # Nodes ohne Standort stehen am Ende.
    return sorted(groups.values(), key=lambda g: (g.name == "", g.name.lower()))
