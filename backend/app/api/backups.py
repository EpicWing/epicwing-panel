import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agentlink import protocol
from app.api.servers import FILES_BLOCKED, _conflict, _exclusive, _not_found, _send
from app.db import get_db
from app.models import Server
from app.models.server import ServerBackup
from app.security.server_access import ServerAccess, ServerPermission, server_access
from app.services import audit, lifecycle

router = APIRouter(prefix="/servers", tags=["backups"])

DbSession = Annotated[Session, Depends(get_db)]
BackupsView = Annotated[ServerAccess, Depends(server_access(ServerPermission.BACKUPS_VIEW))]
BackupsCreate = Annotated[ServerAccess, Depends(server_access(ServerPermission.BACKUPS_CREATE))]
BackupsRestore = Annotated[ServerAccess, Depends(server_access(ServerPermission.BACKUPS_RESTORE))]
BackupsDelete = Annotated[ServerAccess, Depends(server_access(ServerPermission.BACKUPS_DELETE))]

MAX_LISTED = 200
REFRESH_LIMIT = 5

# Übersetzt die Fehlertexte des Agents in saubere Statuscodes.
BACKUP_ERRORS = (
    (
        "already running",
        status.HTTP_409_CONFLICT,
        "Another backup operation is already running for this server.",
    ),
    (
        "a backup operation is running",
        status.HTTP_409_CONFLICT,
        "A backup operation is running for this server.",
    ),
    (
        "too many backup",
        status.HTTP_409_CONFLICT,
        "Too many backup operations are running on this node.",
    ),
    ("already exists", status.HTTP_409_CONFLICT, "This backup already exists."),
    (
        "backup file not found",
        status.HTTP_404_NOT_FOUND,
        "The backup file was not found on the node.",
    ),
    ("too many open commands", status.HTTP_503_SERVICE_UNAVAILABLE, "The node is busy."),
)


class BackupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=128)
    ignored: str = Field(default="", max_length=4096)
    is_locked: bool = False

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if any(ord(c) < 32 for c in value):
            raise ValueError("The name contains control characters.")
        return value or None

    @field_validator("ignored")
    @classmethod
    def _clean_ignored(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("The ignore list contains invalid characters.")
        return value


class BackupPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_locked: bool


class BackupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    size_bytes: int
    sha256: str | None
    is_locked: bool
    ignored: str
    error: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None


class BackupList(BaseModel):
    limit: int
    items: list[BackupOut]


def _data(result: protocol.CommandResult) -> dict[str, Any]:
    if result.ok:
        return result.data or {}
    message = (result.error or "").lower()
    for needle, code, text in BACKUP_ERRORS:
        if needle in message:
            raise HTTPException(code, text)
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY, "The node could not complete the backup operation."
    )


def _params(server: Server, backup: ServerBackup, **extra: Any) -> dict[str, Any]:
    return {"name": lifecycle.container_name(server.id), "id": str(backup.id), **extra}


def _check_available(server: Server) -> None:
    if server.status in FILES_BLOCKED:
        raise _conflict(f"Backups are not available while the server is {server.status}.")


def _get_backup(db: Session, server: Server, backup_id: uuid.UUID) -> ServerBackup:
    backup = db.get(ServerBackup, backup_id)
    if backup is None or backup.server_id != server.id:
        raise _not_found("Backup not found.")
    return backup


def _finish(backup: ServerBackup, state: str, error: str | None = None) -> None:
    backup.status = state
    backup.error = error
    backup.completed_at = datetime.now(UTC)


async def _refresh(db: Session, server: Server, backup: ServerBackup) -> None:
    """Fragt den Stand eines laufenden Backups beim Agent ab und schreibt ihn in die DB."""
    if backup.status != "running":
        return
    try:
        result = await _send(server, "backup.status", _params(server, backup, kind="create"))
    except HTTPException:
        # Die Node ist nicht erreichbar. Der Stand bleibt, wie er war.
        return
    if not result.ok:
        if "not found" in (result.error or "").lower():
            _finish(backup, "failed", "The backup is missing on the node.")
            db.commit()
        return
    data = result.data or {}
    state = data.get("state")
    if state == "ok":
        backup.size_bytes = int(data.get("size") or 0)
        backup.sha256 = str(data["sha256"]) if data.get("sha256") else None
        _finish(backup, "ok")
    elif state == "failed":
        _finish(backup, "failed", str(data.get("error") or "The backup failed.")[:1024])
    else:
        return
    db.commit()


def _audit(
    db: Session, request: Request, auth: ServerAccess, action: str, backup_name: str
) -> None:
    audit.record(
        db,
        f"server.backup.{action}",
        actor_id=auth.user.id,
        target_type="server",
        target_id=str(auth.server.id),
        ip=audit.client_ip(request),
        details={"name": auth.server.name, "backup": backup_name},
    )
    db.commit()


@router.get("/{server_id}/backups")
async def list_backups(auth: BackupsView, db: DbSession) -> BackupList:
    server = auth.server
    rows = list(
        db.scalars(
            select(ServerBackup)
            .where(ServerBackup.server_id == server.id)
            .order_by(ServerBackup.created_at.desc())
            .limit(MAX_LISTED)
        )
    )
    for row in [r for r in rows if r.status == "running"][:REFRESH_LIMIT]:
        await _refresh(db, server, row)
    return BackupList(limit=server.backup_limit, items=[BackupOut.model_validate(r) for r in rows])


@router.post("/{server_id}/backups", status_code=status.HTTP_201_CREATED)
async def create_backup(
    body: BackupCreate, request: Request, auth: BackupsCreate, db: DbSession
) -> BackupOut:
    server = auth.server
    _check_available(server)
    if server.backup_limit <= 0:
        raise _conflict("Backups are disabled for this server.")
    async with _exclusive(server.id):
        used = (
            db.scalar(
                select(func.count())
                .select_from(ServerBackup)
                .where(ServerBackup.server_id == server.id, ServerBackup.status != "failed")
            )
            or 0
        )
        if used >= server.backup_limit:
            raise _conflict("The backup limit for this server is reached.")
        name = body.name or datetime.now(UTC).strftime("Backup %Y-%m-%d %H:%M")
        backup = ServerBackup(
            id=uuid.uuid4(),
            server_id=server.id,
            created_by=auth.user.id,
            name=name,
            status="running",
            ignored=body.ignored,
            is_locked=body.is_locked,
        )
        db.add(backup)
        db.commit()
        try:
            result = await _send(
                server, "backup.create", _params(server, backup, ignored=backup.ignored)
            )
            _data(result)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_504_GATEWAY_TIMEOUT:
                # Der Agent kann schon arbeiten. Der Eintrag bleibt als fehlgeschlagen sichtbar.
                _finish(backup, "failed", "The node did not answer in time.")
            else:
                db.delete(backup)
            db.commit()
            raise
    _audit(db, request, auth, "create", name)
    db.refresh(backup)
    return BackupOut.model_validate(backup)


@router.get("/{server_id}/backups/{backup_id}")
async def get_backup(backup_id: uuid.UUID, auth: BackupsView, db: DbSession) -> BackupOut:
    backup = _get_backup(db, auth.server, backup_id)
    await _refresh(db, auth.server, backup)
    return BackupOut.model_validate(backup)


@router.patch("/{server_id}/backups/{backup_id}")
def patch_backup(
    backup_id: uuid.UUID,
    body: BackupPatch,
    request: Request,
    auth: BackupsDelete,
    db: DbSession,
) -> BackupOut:
    backup = _get_backup(db, auth.server, backup_id)
    backup.is_locked = body.is_locked
    db.commit()
    _audit(db, request, auth, "lock" if body.is_locked else "unlock", backup.name)
    db.refresh(backup)
    return BackupOut.model_validate(backup)


@router.post("/{server_id}/backups/{backup_id}/restore", status_code=status.HTTP_202_ACCEPTED)
async def restore_backup(
    backup_id: uuid.UUID, request: Request, auth: BackupsRestore, db: DbSession
) -> dict[str, str]:
    server = auth.server
    _check_available(server)
    if server.status != "offline":
        raise _conflict("Stop the server before restoring a backup.")
    backup = _get_backup(db, server, backup_id)
    if backup.status != "ok":
        raise _conflict("Only finished backups can be restored.")
    async with _exclusive(server.id):
        result = await _send(
            server, "backup.restore", _params(server, backup, sha256=backup.sha256 or "")
        )
        _data(result)
    _audit(db, request, auth, "restore", backup.name)
    return {"state": "running"}


@router.get("/{server_id}/backups/{backup_id}/restore")
async def restore_status(
    backup_id: uuid.UUID, auth: BackupsRestore, db: DbSession
) -> dict[str, str | None]:
    backup = _get_backup(db, auth.server, backup_id)
    result = await _send(auth.server, "backup.status", _params(auth.server, backup, kind="restore"))
    data = _data(result)
    return {"state": str(data.get("state") or "unknown"), "error": data.get("error") or None}


@router.delete("/{server_id}/backups/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(
    backup_id: uuid.UUID, request: Request, auth: BackupsDelete, db: DbSession
) -> None:
    server = auth.server
    backup = _get_backup(db, server, backup_id)
    if backup.is_locked:
        raise _conflict("This backup is locked.")
    await _refresh(db, server, backup)
    if backup.status == "running":
        raise _conflict("Wait until the backup is finished.")
    name = backup.name
    async with _exclusive(server.id):
        result = await _send(server, "backup.delete", _params(server, backup))
        _data(result)
    db.delete(backup)
    db.commit()
    _audit(db, request, auth, "delete", name)
