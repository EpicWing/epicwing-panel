"""Öffentliche SSH-Schlüssel verwalten. Nur mit Cookie-Session."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import SshKey
from app.security.sessions import CurrentAuth
from app.security.sshkeys import parse_public_key
from app.services import audit

router = APIRouter(prefix="/ssh-keys", tags=["ssh-keys"])
DbSession = Annotated[Session, Depends(get_db)]

MAX_KEYS = 20


class SshKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    public_key: str = Field(min_length=1, max_length=4096)


class SshKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_type: str
    fingerprint: str
    last_used_at: datetime | None
    created_at: datetime


@router.get("")
def list_keys(auth: CurrentAuth, db: DbSession) -> list[SshKeyOut]:
    rows = db.scalars(
        select(SshKey).where(SshKey.user_id == auth.user.id).order_by(SshKey.created_at)
    )
    return [SshKeyOut.model_validate(row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_key(
    body: SshKeyCreate, request: Request, auth: CurrentAuth, db: DbSession
) -> SshKeyOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "The name must not be empty.")
    try:
        key_type, public_key, fingerprint = parse_public_key(body.public_key)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    count = db.scalar(
        select(func.count()).select_from(SshKey).where(SshKey.user_id == auth.user.id)
    )
    if (count or 0) >= MAX_KEYS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"You can have at most {MAX_KEYS} SSH keys.")
    if db.scalar(select(SshKey.id).where(SshKey.fingerprint == fingerprint)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This key is already registered.")

    key = SshKey(
        user_id=auth.user.id,
        name=name,
        key_type=key_type,
        public_key=public_key,
        fingerprint=fingerprint,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    audit.record(
        db,
        "ssh_key.create",
        actor_id=auth.user.id,
        ip=audit.client_ip(request),
        details={"name": name, "fingerprint": fingerprint},
    )
    return SshKeyOut.model_validate(key)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_key(key_id: uuid.UUID, request: Request, auth: CurrentAuth, db: DbSession) -> None:
    key = db.get(SshKey, key_id)
    if key is None or key.user_id != auth.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SSH key not found.")
    details = {"name": key.name, "fingerprint": key.fingerprint}
    db.delete(key)
    db.commit()
    audit.record(
        db,
        "ssh_key.delete",
        actor_id=auth.user.id,
        ip=audit.client_ip(request),
        details=details,
    )
