import asyncio
import base64
import logging
import secrets
import uuid
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.agentlink import protocol
from app.agentlink.commands import AgentOffline, broker
from app.api.servers import FILES_BLOCKED, _conflict, _exclusive, _not_found, _send
from app.db import get_db, get_engine
from app.models import Server
from app.models.server import ServerBackup
from app.security.server_access import (
    ServerAccess,
    ServerPermission,
    effective_permissions,
    server_access,
)
from app.services import audit, lifecycle, s3

router = APIRouter(prefix="/servers", tags=["backups"])

DbSession = Annotated[Session, Depends(get_db)]
BackupsView = Annotated[ServerAccess, Depends(server_access(ServerPermission.BACKUPS_VIEW))]
BackupsCreate = Annotated[ServerAccess, Depends(server_access(ServerPermission.BACKUPS_CREATE))]
BackupsRestore = Annotated[ServerAccess, Depends(server_access(ServerPermission.BACKUPS_RESTORE))]
BackupsDelete = Annotated[ServerAccess, Depends(server_access(ServerPermission.BACKUPS_DELETE))]
BackupsDownload = Annotated[ServerAccess, Depends(server_access(ServerPermission.BACKUPS_DOWNLOAD))]

MAX_LISTED = 200
REFRESH_LIMIT = 5

log = logging.getLogger(__name__)

# Object storage. The list of upload links must fit into one message to the node.
PART_MIN = 64 * 1024 * 1024
PART_MAX = 5 * 1024 * 1024 * 1024
MAX_PARTS = 1000
LINK_SECONDS = 12 * 3600
DOWNLOAD_LINK_SECONDS = 600
REMOTE_INTERVAL = 15
FETCH_POLL_SECONDS = 3
FETCH_POLLS = LINK_SECONDS // FETCH_POLL_SECONDS

# Restores that first download the archive from the object storage.
_fetching: dict[uuid.UUID, asyncio.Task[None]] = {}
_fetch_errors: dict[uuid.UUID, str] = {}

# Turns the error texts of the agent into clean status codes.
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


class BackupTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_server_id: uuid.UUID
    name: str | None = Field(default=None, max_length=128)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if any(ord(c) < 32 for c in value):
            raise ValueError("The name contains control characters.")
        return value or None


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
    local: bool
    remote_state: str | None
    remote_error: str | None


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
    """Asks the agent for the state of a running backup and writes it to the DB."""
    if backup.status != "running":
        return
    try:
        result = await _send(server, "backup.status", _params(server, backup, kind="create"))
    except HTTPException:
        # The node is not reachable. The state stays as it was.
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
    if state == "ok":
        await _start_upload(db, server, backup)


def _remote_key(config: s3.S3Config, backup: ServerBackup) -> str:
    return s3.object_key(config, "backups", str(backup.server_id), f"{backup.id}.tar.gz")


def _part_size(size: int) -> int:
    need = -(-max(size, 1) // MAX_PARTS)
    return min(max(PART_MIN, need), PART_MAX)


def _remote_failed(backup: ServerBackup, error: str) -> None:
    backup.remote_state = "failed"
    backup.remote_error = error[:1024]
    backup.remote_upload_id = None


async def _abort(config: s3.S3Config, backup: ServerBackup) -> None:
    if backup.remote_key and backup.remote_upload_id:
        try:
            await asyncio.to_thread(
                s3.abort_multipart, config, backup.remote_key, backup.remote_upload_id
            )
        except s3.S3Error:
            log.warning("could not abort the upload of backup %s", backup.id)
    backup.remote_upload_id = None


async def _start_upload(db: Session, server: Server, backup: ServerBackup) -> None:
    """Starts the upload of a finished backup, when the object storage is on."""
    config = s3.load_config(db)
    if not config.ready or backup.status != "ok" or not backup.local:
        return
    if backup.remote_state is not None:
        return
    part = _part_size(backup.size_bytes)
    count = max(1, -(-backup.size_bytes // part))
    if count > MAX_PARTS:
        _remote_failed(backup, "The backup is too large for the object storage.")
        db.commit()
        return
    key = _remote_key(config, backup)
    try:
        upload_id = await asyncio.to_thread(s3.create_multipart, config, key)
    except s3.S3Error as exc:
        _remote_failed(backup, str(exc))
        db.commit()
        return
    urls = [s3.presign_part(config, key, upload_id, n, LINK_SECONDS) for n in range(1, count + 1)]
    backup.remote_key = key
    backup.remote_upload_id = upload_id
    backup.remote_state = "uploading"
    backup.remote_error = None
    db.commit()
    try:
        result = await _send(
            server, "backup.upload", _params(server, backup, part_size=part, urls=urls)
        )
        failed = None if result.ok else result.error or "The node did not start the upload."
    except HTTPException as exc:
        failed = str(exc.detail)
    if failed:
        await _abort(config, backup)
        _remote_failed(backup, failed)
        db.commit()


async def _refresh_upload(db: Session, server: Server, backup: ServerBackup) -> None:
    """Finishes or cancels a running upload, once the node reports a result."""
    if backup.remote_state != "uploading":
        return
    try:
        result = await _send(server, "backup.status", _params(server, backup, kind="upload"))
    except HTTPException:
        return
    data = (result.data or {}) if result.ok else {}
    state = data.get("state")
    if state == "running":
        return
    config = s3.load_config(db)
    if state == "ok" and backup.remote_key and backup.remote_upload_id:
        etags = [str(tag) for tag in data.get("etags") or []]
        try:
            await asyncio.to_thread(
                s3.complete_multipart, config, backup.remote_key, backup.remote_upload_id, etags
            )
        except s3.S3Error as exc:
            await _abort(config, backup)
            _remote_failed(backup, str(exc))
            db.commit()
            return
        backup.remote_state = "ok"
        backup.remote_upload_id = None
        backup.remote_error = None
        db.commit()
        if not config.keep_local:
            try:
                deleted = await _send(server, "backup.delete", _params(server, backup))
            except HTTPException:
                return
            if deleted.ok:
                backup.local = False
                db.commit()
        return
    await _abort(config, backup)
    _remote_failed(backup, str(data.get("error") or result.error or "The upload failed."))
    db.commit()


async def _advance_all() -> None:
    with Session(get_engine(), expire_on_commit=False) as db:
        rows = list(
            db.scalars(
                select(ServerBackup)
                .where(
                    or_(ServerBackup.status == "running", ServerBackup.remote_state == "uploading")
                )
                .limit(50)
            )
        )
        for backup in rows:
            server = db.get(Server, backup.server_id)
            if server is None:
                continue
            if backup.status == "running":
                await _refresh(db, server, backup)
            else:
                await _refresh_upload(db, server, backup)


async def remote_loop() -> None:
    """Finishes backups and moves them to the object storage, also for scheduled backups."""
    while True:
        try:
            await _advance_all()
        except Exception:
            log.exception("backup step failed")
        await asyncio.sleep(REMOTE_INTERVAL)


async def _fetch_then_restore(server_id: uuid.UUID, backup_id: uuid.UUID) -> None:
    """Waits for the download from the object storage, then starts the restore."""
    try:
        for _ in range(FETCH_POLLS):
            await asyncio.sleep(FETCH_POLL_SECONDS)
            with Session(get_engine(), expire_on_commit=False) as db:
                server = db.get(Server, server_id)
                backup = db.get(ServerBackup, backup_id)
                if server is None or backup is None:
                    return
                try:
                    result = await _send(
                        server, "backup.status", _params(server, backup, kind="fetch")
                    )
                except HTTPException:
                    continue
                data = (result.data or {}) if result.ok else {}
                state = data.get("state")
                if state == "running":
                    continue
                if state != "ok":
                    error = data.get("error") or result.error
                    _fetch_errors[backup_id] = str(error or "The download from the storage failed.")
                    return
                backup.local = True
                db.commit()
                if server.status != "offline":
                    _fetch_errors[backup_id] = (
                        "The server was started during the download. Stop it and restore again."
                    )
                    return
                result = await _send(
                    server, "backup.restore", _params(server, backup, sha256=backup.sha256 or "")
                )
                if not result.ok:
                    _fetch_errors[backup_id] = result.error or "The restore failed."
                return
        _fetch_errors[backup_id] = "The download from the storage took too long."
    except Exception:
        log.exception("restore of backup %s failed", backup_id)
        _fetch_errors[backup_id] = "The restore failed."
    finally:
        _fetching.pop(backup_id, None)


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
    # Only uploads that were already running: one started just now has nothing to report.
    uploading = [r for r in rows if r.remote_state == "uploading"][:REFRESH_LIMIT]
    for row in [r for r in rows if r.status == "running"][:REFRESH_LIMIT]:
        await _refresh(db, server, row)
    for row in uploading:
        await _refresh_upload(db, server, row)
    return BackupList(limit=server.backup_limit, items=[BackupOut.model_validate(r) for r in rows])


async def perform_backup(
    db: Session,
    server: Server,
    name: str | None,
    ignored: str,
    is_locked: bool,
    created_by: uuid.UUID | None,
) -> ServerBackup:
    """Creates a backup. The endpoint and the schedules use the same logic."""
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
        name = name or datetime.now(UTC).strftime("Backup %Y-%m-%d %H:%M")
        backup = ServerBackup(
            id=uuid.uuid4(),
            server_id=server.id,
            created_by=created_by,
            name=name,
            status="running",
            ignored=ignored,
            is_locked=is_locked,
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
                # The agent may already be working. The entry stays visible as failed.
                _finish(backup, "failed", "The node did not answer in time.")
            else:
                db.delete(backup)
            db.commit()
            raise
    return backup


@router.post("/{server_id}/backups", status_code=status.HTTP_201_CREATED)
async def create_backup(
    body: BackupCreate, request: Request, auth: BackupsCreate, db: DbSession
) -> BackupOut:
    server = auth.server
    backup = await perform_backup(db, server, body.name, body.ignored, body.is_locked, auth.user.id)
    _audit(db, request, auth, "create", backup.name)
    db.refresh(backup)
    return BackupOut.model_validate(backup)


@router.get("/{server_id}/backups/{backup_id}")
async def get_backup(backup_id: uuid.UUID, auth: BackupsView, db: DbSession) -> BackupOut:
    backup = _get_backup(db, auth.server, backup_id)
    await _refresh(db, auth.server, backup)
    await _refresh_upload(db, auth.server, backup)
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


@router.post("/{server_id}/backups/{backup_id}/upload")
async def retry_upload(
    backup_id: uuid.UUID, request: Request, auth: BackupsCreate, db: DbSession
) -> BackupOut:
    """Tries the upload to the object storage again."""
    server = auth.server
    backup = _get_backup(db, server, backup_id)
    if not s3.load_config(db).ready:
        raise _conflict("The object storage is not set up.")
    if backup.status != "ok" or not backup.local or backup.remote_state not in (None, "failed"):
        raise _conflict("This backup cannot be uploaded now.")
    _check_available(server)
    backup.remote_state = None
    backup.remote_error = None
    db.commit()
    await _start_upload(db, server, backup)
    _audit(db, request, auth, "upload", backup.name)
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
    if backup.id in _fetching:
        raise _conflict("This backup is already being restored.")
    if not backup.local:
        if backup.remote_state != "ok" or not backup.remote_key:
            raise _conflict("The backup file is not available.")
        url = s3.presign_get(s3.load_config(db), backup.remote_key, LINK_SECONDS)
        async with _exclusive(server.id):
            fetched = _data(
                await _send(
                    server,
                    "backup.fetch",
                    _params(server, backup, url=url, sha256=backup.sha256 or ""),
                )
            )
        if fetched.get("state") != "ok":
            _fetch_errors.pop(backup.id, None)
            _fetching[backup.id] = asyncio.create_task(_fetch_then_restore(server.id, backup.id))
            _audit(db, request, auth, "restore", backup.name)
            return {"state": "running"}
        backup.local = True
        db.commit()
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
    if backup.id in _fetch_errors:
        return {"state": "failed", "error": _fetch_errors.pop(backup.id)}
    if backup.id in _fetching:
        return {"state": "running", "error": None}
    result = await _send(auth.server, "backup.status", _params(auth.server, backup, kind="restore"))
    data = _data(result)
    return {"state": str(data.get("state") or "unknown"), "error": data.get("error") or None}


@router.post("/{server_id}/backups/{backup_id}/transfer", status_code=status.HTTP_201_CREATED)
async def transfer_backup(
    backup_id: uuid.UUID,
    body: BackupTransfer,
    request: Request,
    auth: BackupsDownload,
    db: DbSession,
) -> BackupOut:
    """Copies a finished backup to another server on the same node."""
    source = auth.server
    _check_available(source)
    original = _get_backup(db, source, backup_id)
    if original.status != "ok":
        raise _conflict("Only finished backups can be transferred.")
    if not original.local:
        raise _conflict("This backup is only in the object storage. Restore or download it.")
    target = db.get(Server, body.target_server_id)
    if target is None:
        raise _not_found("Server not found.")
    granted = effective_permissions(db, auth.user, [target], auth.is_admin)[target.id]
    if not granted:
        raise _not_found("Server not found.")
    if ServerPermission.BACKUPS_CREATE.value not in granted:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied.")
    if target.id == source.id:
        raise _conflict("Choose a different target server.")
    if target.node_id != source.node_id:
        raise _conflict("Transfers between different nodes are not supported yet.")
    _check_available(target)
    if target.backup_limit <= 0:
        raise _conflict("Backups are disabled for the target server.")
    async with _exclusive(target.id):
        used = (
            db.scalar(
                select(func.count())
                .select_from(ServerBackup)
                .where(ServerBackup.server_id == target.id, ServerBackup.status != "failed")
            )
            or 0
        )
        if used >= target.backup_limit:
            raise _conflict("The backup limit of the target server is reached.")
        name = body.name or f"{original.name} (from {source.name})"[:128]
        new_backup = ServerBackup(
            id=uuid.uuid4(),
            server_id=target.id,
            created_by=auth.user.id,
            name=name,
            status="running",
            ignored=original.ignored,
            is_locked=False,
        )
        db.add(new_backup)
        db.commit()
        try:
            result = await _send(
                target,
                "backup.copy",
                {
                    "name": lifecycle.container_name(target.id),
                    "id": str(new_backup.id),
                    "source_name": lifecycle.container_name(source.id),
                    "source_id": str(original.id),
                    "sha256": original.sha256 or "",
                },
            )
            _data(result)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_504_GATEWAY_TIMEOUT:
                _finish(new_backup, "failed", "The node did not answer in time.")
            else:
                db.delete(new_backup)
            db.commit()
            raise
    _audit(db, request, auth, "transfer", f"{original.name} -> {target.name}")
    db.refresh(new_backup)
    return BackupOut.model_validate(new_backup)


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
    await _refresh_upload(db, server, backup)
    if backup.remote_state == "uploading":
        raise _conflict("Wait until the upload is finished.")
    name = backup.name
    if backup.remote_state == "ok" and backup.remote_key:
        try:
            await asyncio.to_thread(s3.delete_object, s3.load_config(db), backup.remote_key)
        except s3.S3Error as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"The object storage refused the delete: {exc}"
            ) from None
    if backup.local:
        async with _exclusive(server.id):
            result = await _send(server, "backup.delete", _params(server, backup))
            _data(result)
    db.delete(backup)
    db.commit()
    _audit(db, request, auth, "delete", name)


DOWNLOAD_CHUNK = 8 * 1024  # a reply from the node must stay below the message limit
DOWNLOAD_WINDOW = 3  # chunks requested from the node at the same time
DOWNLOAD_RETRIES = 4


def _download_name() -> str:
    return f"backup-{secrets.token_hex(4)}.tar.gz"


def _chunk(data: dict[str, Any]) -> bytes:
    try:
        return base64.b64decode(str(data.get("data", "")), validate=True)
    except ValueError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The node sent an invalid chunk."
        ) from None


async def _read_archive(node_id: uuid.UUID, params: dict[str, Any], offset: int) -> dict[str, Any]:
    attempt = 0
    while True:
        try:
            result = await broker.send(
                node_id, "backup.read", {**params, "offset": offset, "length": DOWNLOAD_CHUNK}
            )
        except (AgentOffline, TimeoutError):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "The node is not reachable."
            ) from None
        attempt += 1
        busy = "too many open commands" in (result.error or "").lower()
        if result.ok or not busy or attempt >= DOWNLOAD_RETRIES:
            return _data(result)
        await asyncio.sleep(0.2 * attempt)


async def _fetch_chunk(
    node_id: uuid.UUID, params: dict[str, Any], offset: int, expected: int
) -> bytes:
    data = _chunk(await _read_archive(node_id, params, offset))
    if len(data) != expected:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The node sent an incomplete chunk.")
    return data


async def _archive_chunks(
    node_id: uuid.UUID, params: dict[str, Any], first: bytes, size: int
) -> AsyncIterator[bytes]:
    """Streams the archive in order while a few more chunks are already on their way."""
    if first:
        yield first
    sent = len(first)
    requested = sent
    pending: deque[asyncio.Task[bytes]] = deque()
    try:
        while sent < size:
            while requested < size and len(pending) < DOWNLOAD_WINDOW:
                expected = min(DOWNLOAD_CHUNK, size - requested)
                pending.append(
                    asyncio.create_task(_fetch_chunk(node_id, params, requested, expected))
                )
                requested += expected
            data = await pending.popleft()
            yield data
            sent += len(data)
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


@router.get("/{server_id}/backups/{backup_id}/download")
async def download_backup(
    backup_id: uuid.UUID, request: Request, auth: BackupsDownload, db: DbSession
) -> Response:
    server = auth.server
    backup = _get_backup(db, server, backup_id)
    if backup.status == "ok" and backup.remote_state == "ok" and backup.remote_key:
        # Straight from the bucket: faster, and no load on the panel and the node.
        url = s3.presign_get(
            s3.load_config(db), backup.remote_key, DOWNLOAD_LINK_SECONDS, _download_name()
        )
        _audit(db, request, auth, "download", backup.name)
        return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    _check_available(server)
    if backup.status != "ok":
        raise _conflict("Only finished backups can be downloaded.")
    # Plain values only: the streaming part must not touch database objects.
    node_id = server.node_id
    params = _params(server, backup)
    filename = _download_name()
    name = backup.name
    first = _data(
        await _send(server, "backup.read", {**params, "offset": 0, "length": DOWNLOAD_CHUNK})
    )
    size = first.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The node sent an invalid size.")
    head = _chunk(first)
    if len(head) != min(DOWNLOAD_CHUNK, size):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The node sent an incomplete chunk.")
    _audit(db, request, auth, "download", name)
    return StreamingResponse(
        _archive_chunks(node_id, params, head, size),
        media_type="application/gzip",
        headers={
            "Content-Length": str(size),
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
