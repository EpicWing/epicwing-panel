"""Admin: S3-compatible storage for backups, with a connection test."""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.security.permissions import AdminAuth
from app.services import audit, s3

router = APIRouter(prefix="/admin/storage", tags=["admin"])
DbSession = Annotated[Session, Depends(get_db)]

ENDPOINT_RE = re.compile(r"https?://[A-Za-z0-9.-]+(:\d{1,5})?")
REGION_RE = re.compile(r"[a-z0-9-]{1,32}")
BUCKET_RE = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
PREFIX_RE = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")


def _line(value: str) -> str:
    value = value.strip()
    if any(ord(c) < 32 for c in value):
        raise ValueError("Line breaks and control characters are not allowed.")
    return value


class StorageOut(BaseModel):
    enabled: bool
    endpoint: str
    region: str
    bucket: str
    prefix: str
    access_key: str
    secret_key_set: bool
    path_style: bool
    keep_local: bool
    ready: bool


class StorageIn(BaseModel):
    enabled: bool = False
    endpoint: str = Field("", max_length=255)
    region: str = Field("auto", max_length=32)
    bucket: str = Field("", max_length=63)
    prefix: str = Field("epicwing", max_length=128)
    access_key: str = Field("", max_length=128)
    # None keeps the saved secret.
    secret_key: str | None = Field(None, max_length=256)
    path_style: bool = True
    keep_local: bool = False

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, value: str) -> str:
        value = _line(value).rstrip("/")
        if value and not ENDPOINT_RE.fullmatch(value):
            raise ValueError(
                "Enter the endpoint without a path, like https://s3.eu-central-1.amazonaws.com."
            )
        return value

    @field_validator("region")
    @classmethod
    def _region(cls, value: str) -> str:
        value = _line(value).lower() or "auto"
        if not REGION_RE.fullmatch(value):
            raise ValueError("The region may only use a-z, 0-9 and hyphens.")
        return value

    @field_validator("bucket")
    @classmethod
    def _bucket(cls, value: str) -> str:
        value = _line(value).lower()
        if value and not BUCKET_RE.fullmatch(value):
            raise ValueError("The bucket name may only use a-z, 0-9, dots and hyphens.")
        return value

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        value = _line(value).strip("/")
        if value and (not PREFIX_RE.fullmatch(value) or ".." in value.split("/")):
            raise ValueError("The folder may only use letters, digits, dots, hyphens and slashes.")
        return value

    @field_validator("access_key")
    @classmethod
    def _key(cls, value: str) -> str:
        return _line(value)

    @field_validator("secret_key")
    @classmethod
    def _secret(cls, value: str | None) -> str | None:
        return None if value is None else _line(value) or None

    @model_validator(mode="after")
    def _complete(self) -> "StorageIn":
        if self.enabled and not (self.endpoint and self.bucket and self.access_key):
            raise ValueError("Endpoint, bucket and access key are needed to turn the storage on.")
        return self


class StorageTestOut(BaseModel):
    ok: bool
    detail: str


def _out(db: Session) -> StorageOut:
    config = s3.load_config(db)
    return StorageOut(
        enabled=config.enabled,
        endpoint=config.endpoint,
        region=config.region,
        bucket=config.bucket,
        prefix=config.prefix,
        access_key=config.access_key,
        secret_key_set=bool(config.secret_key),
        path_style=config.path_style,
        keep_local=config.keep_local,
        ready=config.ready,
    )


@router.get("")
def get_storage(_auth: AdminAuth, db: DbSession) -> StorageOut:
    return _out(db)


@router.put("")
def put_storage(body: StorageIn, request: Request, auth: AdminAuth, db: DbSession) -> StorageOut:
    s3.save_config(db, body.model_dump())
    audit.record(
        db,
        "admin.storage.update",
        actor_id=auth.user.id,
        ip=audit.client_ip(request),
        details={"enabled": body.enabled, "endpoint": body.endpoint, "bucket": body.bucket},
    )
    db.commit()
    return _out(db)


@router.post("/test")
def test_storage(_auth: AdminAuth, db: DbSession) -> StorageTestOut:
    try:
        return StorageTestOut(ok=True, detail=s3.check(s3.load_config(db)))
    except s3.S3Error as exc:
        return StorageTestOut(ok=False, detail=str(exc))
