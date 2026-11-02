"""Permissions on single servers.

Who may do what on a server?
- Global administrators (is_admin or the projects.manage permission): everything.
- The owner (servers.owner_id): all server permissions.
- Members (server_members): their stored permissions, plus server.view at all times.
- Everyone else: nothing. The server is invisible to them (404 instead of 403).
"""

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, Server, User, UserSession
from app.models.server import ServerMember, ServerMemberPermission
from app.security.apikeys import KeyContext, ServerAuth
from app.security.permissions import Permission, has_permission


class ServerPermission(StrEnum):
    VIEW = "server.view"
    CONSOLE_VIEW = "console.view"
    CONSOLE_COMMAND = "console.command"
    POWER_START = "power.start"
    POWER_STOP = "power.stop"
    POWER_RESTART = "power.restart"
    FILES_READ = "files.read"
    FILES_WRITE = "files.write"
    STARTUP_VIEW = "startup.view"
    STARTUP_UPDATE = "startup.update"
    SETTINGS_VIEW = "settings.view"
    SETTINGS_UPDATE = "settings.update"
    SETTINGS_REINSTALL = "settings.reinstall"
    BACKUPS_VIEW = "backups.view"
    BACKUPS_CREATE = "backups.create"
    BACKUPS_DOWNLOAD = "backups.download"
    BACKUPS_RESTORE = "backups.restore"
    BACKUPS_DELETE = "backups.delete"
    DATABASES_VIEW = "databases.view"
    DATABASES_MANAGE = "databases.manage"
    ALLOCATIONS_VIEW = "allocations.view"
    ALLOCATIONS_MANAGE = "allocations.manage"
    SCHEDULES_VIEW = "schedules.view"
    SCHEDULES_MANAGE = "schedules.manage"
    ACCESS_VIEW = "access.view"
    ACCESS_MANAGE = "access.manage"


ALL_SERVER_PERMISSIONS: frozenset[str] = frozenset(p.value for p in ServerPermission)

# An API key must never touch the access control of a server.
KEY_DENIED = frozenset({ServerPermission.ACCESS_VIEW, ServerPermission.ACCESS_MANAGE})


def is_server_admin(db: Session, user: User) -> bool:
    return has_permission(db, user, Permission.PROJECTS_MANAGE)


def member_permissions(
    db: Session, user_id: uuid.UUID, server_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, set[str]]:
    """Permissions as a member, per server. Unknown stored values grant nothing."""
    ids = list(server_ids)
    result: dict[uuid.UUID, set[str]] = {}
    if not ids:
        return result
    members = db.execute(
        select(ServerMember.id, ServerMember.server_id).where(
            ServerMember.user_id == user_id, ServerMember.server_id.in_(ids)
        )
    ).all()
    server_of = {member_id: server_id for member_id, server_id in members}
    for server_id in server_of.values():
        result[server_id] = {ServerPermission.VIEW.value}
    if server_of:
        rows = db.execute(
            select(ServerMemberPermission.member_id, ServerMemberPermission.permission).where(
                ServerMemberPermission.member_id.in_(list(server_of))
            )
        )
        for member_id, permission in rows:
            if permission in ALL_SERVER_PERMISSIONS:
                result[server_of[member_id]].add(permission)
    return result


def effective_permissions(
    db: Session, user: User, servers: list[Server], admin: bool | None = None
) -> dict[uuid.UUID, set[str]]:
    """What the user may do on each of the servers. Empty means: no access."""
    if admin is None:
        admin = is_server_admin(db, user)
    if admin:
        return {server.id: set(ALL_SERVER_PERMISSIONS) for server in servers}
    shared = member_permissions(db, user.id, [s.id for s in servers if s.owner_id != user.id])
    result: dict[uuid.UUID, set[str]] = {}
    for server in servers:
        if server.owner_id == user.id:
            result[server.id] = set(ALL_SERVER_PERMISSIONS)
        else:
            result[server.id] = shared.get(server.id, set())
    return result


def visible_servers(db: Session, user: User) -> Select[tuple[Server]]:
    """All servers the user may see."""
    query = select(Server)
    if is_server_admin(db, user):
        return query
    member_of = select(ServerMember.server_id).where(ServerMember.user_id == user.id)
    return query.where(or_(Server.owner_id == user.id, Server.id.in_(member_of)))


@dataclass
class ServerAccess:
    user: User
    session: UserSession | None
    server: Server
    permissions: set[str]
    is_admin: bool
    api_key: ApiKey | None = None

    def has(self, permission: ServerPermission) -> bool:
        return permission.value in self.permissions

    def require(self, permission: ServerPermission) -> None:
        if not self.has(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied.")


def server_access(permission: ServerPermission | None = None) -> Callable[..., ServerAccess]:
    """Dependency for endpoints with server_id: access to the server, optionally a permission."""

    def dependency(
        server_id: uuid.UUID,
        auth: ServerAuth,
        db: Annotated[Session, Depends(get_db)],
    ) -> ServerAccess:
        if isinstance(auth, KeyContext) and permission in KEY_DENIED:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "API keys cannot manage server access.")
        server = db.get(Server, server_id)
        if server is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Server not found.")
        admin = is_server_admin(db, auth.user)
        granted = effective_permissions(db, auth.user, [server], admin)[server.id]
        if not granted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Server not found.")
        key = auth.key if isinstance(auth, KeyContext) else None
        access = ServerAccess(auth.user, auth.session, server, granted, admin, key)
        if permission is not None:
            access.require(permission)
        return access

    return dependency
