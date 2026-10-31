"""Databases of a server: create, renew password, delete."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.servers import _conflict, _not_found
from app.db import get_db
from app.models import DatabaseHost, ServerDatabase
from app.security.server_access import ServerAccess, ServerPermission, server_access
from app.security.vault import decrypt_text, encrypt_text
from app.services import audit, dbhost
from app.services.server_databases import PASSWORD_PURPOSE, database_name, endpoint_for

router = APIRouter(prefix="/servers", tags=["databases"])

DbSession = Annotated[Session, Depends(get_db)]
DatabasesView = Annotated[ServerAccess, Depends(server_access(ServerPermission.DATABASES_VIEW))]
DatabasesManage = Annotated[ServerAccess, Depends(server_access(ServerPermission.DATABASES_MANAGE))]

# Fixed value per server; a setting for the limit comes later.
PER_SERVER_LIMIT = 10


class DatabaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    remote: str = Field("", max_length=255, validate_default=True)

    @field_validator("remote")
    @classmethod
    def _remote(cls, value: str) -> str:
        value = value.strip() or "%"
        if not dbhost.REMOTE_RE.match(value):
            raise ValueError("Use an IP address, a host name or % as wildcard")
        return value


class DatabaseOut(BaseModel):
    id: uuid.UUID
    name: str
    username: str
    remote: str
    host: str
    port: int
    password: str


class DatabaseList(BaseModel):
    limit: int
    items: list[DatabaseOut]


def _out(row: ServerDatabase, host: DatabaseHost) -> DatabaseOut:
    return DatabaseOut(
        id=row.id,
        name=row.name,
        username=row.username,
        remote=row.remote,
        host=host.host,
        port=host.port,
        password=decrypt_text(row.password, PASSWORD_PURPOSE) or "",
    )


def _row(db: Session, server_id: uuid.UUID, database_id: uuid.UUID) -> ServerDatabase:
    row = db.get(ServerDatabase, database_id)
    if row is None or row.server_id != server_id:
        raise _not_found("Database not found.")
    return row


def _count(db: Session, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(ServerDatabase).where(*conditions)) or 0


def _pick_host(db: Session) -> DatabaseHost | None:
    hosts = db.scalars(select(DatabaseHost).order_by(DatabaseHost.created_at, DatabaseHost.name))
    for host in hosts:
        if host.max_databases is None or _count(db, ServerDatabase.host_id == host.id) < (
            host.max_databases
        ):
            return host
    return None


def _host_error(exc: dbhost.HostError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.get("/{server_id}/databases", response_model=DatabaseList)
def list_databases(server_id: uuid.UUID, access: DatabasesView, db: DbSession) -> DatabaseList:
    rows = db.scalars(
        select(ServerDatabase)
        .where(ServerDatabase.server_id == access.server.id)
        .order_by(ServerDatabase.created_at, ServerDatabase.name)
    ).all()
    hosts = {row.host_id: db.get(DatabaseHost, row.host_id) for row in rows}
    return DatabaseList(
        limit=PER_SERVER_LIMIT, items=[_out(row, hosts[row.host_id]) for row in rows]
    )


@router.post(
    "/{server_id}/databases", response_model=DatabaseOut, status_code=status.HTTP_201_CREATED
)
def add_database(
    server_id: uuid.UUID,
    body: DatabaseCreate,
    request: Request,
    access: DatabasesManage,
    db: DbSession,
) -> DatabaseOut:
    server = access.server
    if _count(db, ServerDatabase.server_id == server.id) >= PER_SERVER_LIMIT:
        raise _conflict("This server reached its database limit.")
    host = _pick_host(db)
    if host is None:
        raise _conflict("No database host is available. An administrator has to add one.")
    name = database_name(server.id, body.name)
    username = dbhost.random_username()
    password = dbhost.new_password()
    row = ServerDatabase(
        server_id=server.id,
        host_id=host.id,
        name=name,
        username=username,
        remote=body.remote,
        password=encrypt_text(password, PASSWORD_PURPOSE),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise _conflict("A database with this name already exists.") from exc
    try:
        dbhost.create_database(endpoint_for(host), name, username, body.remote, password)
    except dbhost.HostError as exc:
        db.rollback()
        raise _host_error(exc) from exc
    db.commit()
    audit.record(
        db,
        "server.database.create",
        actor_id=access.user.id,
        target_type="server",
        target_id=str(server.id),
        ip=audit.client_ip(request),
        details={"database": name},
    )
    return _out(row, host)


@router.post("/{server_id}/databases/{database_id}/rotate", response_model=DatabaseOut)
def rotate_password(
    server_id: uuid.UUID,
    database_id: uuid.UUID,
    request: Request,
    access: DatabasesManage,
    db: DbSession,
) -> DatabaseOut:
    row = _row(db, access.server.id, database_id)
    host = db.get(DatabaseHost, row.host_id)
    password = dbhost.new_password()
    try:
        dbhost.set_password(endpoint_for(host), row.username, row.remote, password)
    except dbhost.HostError as exc:
        raise _host_error(exc) from exc
    row.password = encrypt_text(password, PASSWORD_PURPOSE)
    db.commit()
    audit.record(
        db,
        "server.database.rotate",
        actor_id=access.user.id,
        target_type="server",
        target_id=str(access.server.id),
        ip=audit.client_ip(request),
        details={"database": row.name},
    )
    return _out(row, host)


@router.delete("/{server_id}/databases/{database_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_database(
    server_id: uuid.UUID,
    database_id: uuid.UUID,
    request: Request,
    access: DatabasesManage,
    db: DbSession,
) -> None:
    row = _row(db, access.server.id, database_id)
    host = db.get(DatabaseHost, row.host_id)
    name = row.name
    try:
        dbhost.drop_database(endpoint_for(host), name, row.username, row.remote)
    except dbhost.HostError as exc:
        raise _host_error(exc) from exc
    db.delete(row)
    db.commit()
    audit.record(
        db,
        "server.database.delete",
        actor_id=access.user.id,
        target_type="server",
        target_id=str(access.server.id),
        ip=audit.client_ip(request),
        details={"database": name},
    )
