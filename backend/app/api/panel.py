"""Panel-Einstellungen: öffentlicher Name und optionale Hilfe-Links (nur Admins ändern)."""

from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PanelSetting
from app.security.permissions import AdminAuth
from app.services import audit

router = APIRouter(tags=["panel"])
DbSession = Annotated[Session, Depends(get_db)]

DEFAULTS = {
    "name": "EpicWing",
    "discord_url": "",
    "docs_url": "",
    "github_url": "",
    "support_url": "",
}
URL_FIELDS = ("discord_url", "docs_url", "github_url", "support_url")


class PanelInfo(BaseModel):
    name: str


class PanelSettingsOut(BaseModel):
    name: str
    discord_url: str
    docs_url: str
    github_url: str
    support_url: str


class PanelSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=40)
    discord_url: str = Field(default="", max_length=300)
    docs_url: str = Field(default="", max_length=300)
    github_url: str = Field(default="", max_length=300)
    support_url: str = Field(default="", max_length=300)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("Enter a name without control characters.")
        return value

    @field_validator(*URL_FIELDS)
    @classmethod
    def _check_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        parsed = urlparse(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or any(c.isspace() or ord(c) < 32 for c in value)
        ):
            raise ValueError("Enter a full web address starting with https://.")
        return value


def _load(db: Session) -> dict[str, str]:
    stored = {row.key: row.value for row in db.scalars(select(PanelSetting))}
    return {key: stored.get(key, default) for key, default in DEFAULTS.items()}


@router.get("/panel")
def panel_info(db: DbSession) -> PanelInfo:
    return PanelInfo(name=_load(db)["name"])


@router.get("/admin/settings")
def read_settings(_auth: AdminAuth, db: DbSession) -> PanelSettingsOut:
    return PanelSettingsOut(**_load(db))


@router.put("/admin/settings")
def update_settings(
    body: PanelSettingsIn, request: Request, auth: AdminAuth, db: DbSession
) -> PanelSettingsOut:
    current = _load(db)
    new = body.model_dump()
    changed = [key for key in DEFAULTS if new[key] != current[key]]
    for key in changed:
        row = db.get(PanelSetting, key)
        if row is None:
            db.add(PanelSetting(key=key, value=new[key]))
        else:
            row.value = new[key]
    db.commit()
    if changed:
        # Nur die Namen der geänderten Felder, nicht die Werte.
        audit.record(
            db,
            "panel.settings.update",
            actor_id=auth.user.id,
            ip=audit.client_ip(request),
            details={"changed": changed},
        )
    return PanelSettingsOut(**new)
