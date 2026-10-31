"""Admin: database hosts (MariaDB/MySQL) where server databases are created."""

import re
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DatabaseHost, ServerDatabase
from app.security.permissions import AdminAuth
from app.security.vault import encrypt_text
from app.services import audit, dbhost
from app.services.server_databases import HOST_PURPOSE, endpoint_for

router = APIRouter(prefix="/admin/database-hosts", tags=["admin"])
DbSession = Annotated[Session, Depends(get_db)]

HOST_RE = re.compile(r"^[A-Za-z0-9.\-:]+$")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("Must not be empty")
    return value


def _clean_host(value: str | None) -> str | None:
    value = _clean(value)
    if value is not None and not HOST_RE.match(value):
        raise ValueError("Use an IP address or a host name")
    return value


class HostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(3306, ge=1, le=65535)
    admin_user: str = Field(min_length=1, max_length=64)
    admin_password: str = Field(min_length=1, max_length=256)
    max_databases: int | None = Field(None, ge=1, le=100000)

    _name = field_validator("name", "admin_user")(_clean)
    _host = field_validator("host")(_clean_host)


class HostUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=64)
    host: str | None = Field(None, min_length=1, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    admin_user: str | None = Field(None, min_length=1, max_length=64)
    admin_password: str | None = Field(None, min_length=1, max_length=256)
    max_databases: int | None = Field(None, ge=1, le=100000)

    _name = field_validator("name", "admin_user")(_clean)
    _host = field_validator("host")(_clean_host)


class HostOut(BaseModel):
    id: uuid.UUID
    name: str
    host: str
    port: int
    admin_user: str
    max_databases: int | None
    database_count: int
    created_at: datetime


def _out(db: Session, host: DatabaseHost) -> HostOut:
    count = db.scalar(
        select(func.count()).select_from(ServerDatabase).where(ServerDatabase.host_id == host.id)
    )
    return HostOut(
        id=host.id,
        name=host.name,
        host=host.host,
        port=host.port,
        admin_user=host.admin_user,
        max_databases=host.max_databases,
        database_count=count or 0,
        created_at=host.created_at,
    )


def _get(db: Session, host_id: uuid.UUID) -> DatabaseHost:
    host = db.get(DatabaseHost, host_id)
    if host is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database host not found.")
    return host


def _check_connection(endpoint: dbhost.Endpoint) -> None:
    try:
        dbhost.ping(endpoint)
    except dbhost.HostError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _name_taken() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "A database host with this name exists.")


@router.get("", response_model=list[HostOut])
def list_hosts(auth: AdminAuth, db: DbSession) -> list[HostOut]:
    hosts = db.scalars(select(DatabaseHost).order_by(DatabaseHost.created_at, DatabaseHost.name))
    return [_out(db, host) for host in hosts]


@router.post("", response_model=HostOut, status_code=status.HTTP_201_CREATED)
def create_host(body: HostIn, request: Request, auth: AdminAuth, db: DbSession) -> HostOut:
    _check_connection(dbhost.Endpoint(body.host, body.port, body.admin_user, body.admin_password))
    host = DatabaseHost(
        name=body.name,
        host=body.host,
        port=body.port,
        admin_user=body.admin_user,
        admin_password=encrypt_text(body.admin_password, HOST_PURPOSE),
        max_databases=body.max_databases,
    )
    db.add(host)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _name_taken() from exc
    audit.record(
        db,
        "database_host.create",
        actor_id=auth.user.id,
        target_type="database_host",
        target_id=str(host.id),
        ip=audit.client_ip(request),
        details={"name": host.name},
    )
    return _out(db, host)


@router.patch("/{host_id}", response_model=HostOut)
def update_host(
    host_id: uuid.UUID, body: HostUpdate, request: Request, auth: AdminAuth, db: DbSession
) -> HostOut:
    host = _get(db, host_id)
    changes = {
        key: value
        for key, value in body.model_dump(exclude_unset=True).items()
        if value is not None or key == "max_databases"
    }
    if {"host", "port", "admin_user", "admin_password"} & changes.keys():
        current = endpoint_for(host)
        _check_connection(
            dbhost.Endpoint(
                changes.get("host", host.host),
                changes.get("port", host.port),
                changes.get("admin_user", host.admin_user),
                changes.get("admin_password", current.password),
            )
        )
    for key, value in changes.items():
        if key == "admin_password":
            host.admin_password = encrypt_text(value, HOST_PURPOSE)
        else:
            setattr(host, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _name_taken() from exc
    audit.record(
        db,
        "database_host.update",
        actor_id=auth.user.id,
        target_type="database_host",
        target_id=str(host.id),
        ip=audit.client_ip(request),
        details={"name": host.name, "fields": sorted(changes)},
    )
    return _out(db, host)


@router.post("/{host_id}/test")
def test_host(host_id: uuid.UUID, auth: AdminAuth, db: DbSession) -> dict[str, object]:
    host = _get(db, host_id)
    try:
        version = dbhost.ping(endpoint_for(host))
    except dbhost.HostError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": version}


@router.delete("/{host_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_host(host_id: uuid.UUID, request: Request, auth: AdminAuth, db: DbSession) -> None:
    host = _get(db, host_id)
    if _out(db, host).database_count:
        raise HTTPException(status.HTTP_409_CONFLICT, "Delete the databases on this host first.")
    name = host.name
    db.delete(host)
    db.commit()
    audit.record(
        db,
        "database_host.delete",
        actor_id=auth.user.id,
        target_type="database_host",
        target_id=str(host_id),
        ip=audit.client_ip(request),
        details={"name": name},
    )
