"""API Keys verwalten. Nur mit Cookie-Session, ein Key kann keine Keys anlegen."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey
from app.security.apikeys import new_key
from app.security.sessions import CurrentAuth
from app.services import audit

router = APIRouter(prefix="/api-keys", tags=["api-keys"])
DbSession = Annotated[Session, Depends(get_db)]

MAX_KEYS = 25


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    read_only: bool = False
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class KeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    read_only: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class KeyCreated(KeyOut):
    # Nur in der Antwort auf das Anlegen, danach nie wieder.
    token: str


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("")
def list_keys(auth: CurrentAuth, db: DbSession) -> list[KeyOut]:
    rows = db.scalars(
        select(ApiKey).where(ApiKey.user_id == auth.user.id).order_by(ApiKey.created_at)
    )
    return [KeyOut.model_validate(row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_key(body: KeyCreate, request: Request, auth: CurrentAuth, db: DbSession) -> KeyCreated:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "The name must not be empty.")
    count = db.scalar(
        select(func.count()).select_from(ApiKey).where(ApiKey.user_id == auth.user.id)
    )
    if (count or 0) >= MAX_KEYS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"You can have at most {MAX_KEYS} API keys.")

    token, prefix, token_hash = new_key()
    expires_at = (
        datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    )
    key = ApiKey(
        user_id=auth.user.id,
        name=name,
        prefix=prefix,
        token_hash=token_hash,
        read_only=body.read_only,
        expires_at=expires_at,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    # Das Token selbst gehört nie ins Audit-Log.
    audit.record(
        db,
        "api_key.create",
        actor_id=auth.user.id,
        ip=_ip(request),
        details={"name": name, "read_only": body.read_only},
    )
    return KeyCreated(**KeyOut.model_validate(key).model_dump(), token=token)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_key(key_id: uuid.UUID, request: Request, auth: CurrentAuth, db: DbSession) -> None:
    key = db.get(ApiKey, key_id)
    if key is None or key.user_id != auth.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found.")
    name = key.name
    db.delete(key)
    db.commit()
    audit.record(
        db, "api_key.delete", actor_id=auth.user.id, ip=_ip(request), details={"name": name}
    )
