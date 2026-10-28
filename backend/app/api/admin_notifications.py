"""Admin: Benachrichtigungskanäle (Discord-Webhook, E-Mail) und Testversand."""

from email.utils import parseaddr
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.security.permissions import AdminAuth
from app.services.mail import is_configured, load_config
from app.services.notify import (
    WEBHOOK_PREFIXES,
    load_settings,
    save_settings,
    send_discord,
    send_email,
)

router = APIRouter(prefix="/admin/notifications", tags=["admin"])
DbSession = Annotated[Session, Depends(get_db)]


class NotifyOut(BaseModel):
    discord_enabled: bool
    discord_webhook_set: bool
    email_enabled: bool
    email_to: str
    email_configured: bool


class NotifyIn(BaseModel):
    discord_enabled: bool
    discord_webhook: str | None = Field(None, max_length=300)
    email_enabled: bool
    email_to: str = Field("", max_length=200)

    @field_validator("discord_webhook")
    @classmethod
    def _check_webhook(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if value == "":
            return ""
        if not value.startswith(WEBHOOK_PREFIXES) or any(c.isspace() for c in value):
            raise ValueError("Enter a Discord webhook URL (https://discord.com/api/webhooks/...)")
        return value

    @field_validator("email_to")
    @classmethod
    def _check_email(cls, value: str) -> str:
        value = value.strip()
        if value == "":
            return ""
        if "\r" in value or "\n" in value or "@" not in parseaddr(value)[1]:
            raise ValueError("Enter a valid email address")
        return value


class NotifyTestIn(BaseModel):
    channel: Literal["discord", "email"]


class NotifyTestOut(BaseModel):
    ok: bool
    detail: str


def _out(db: Session) -> NotifyOut:
    settings = load_settings(db)
    return NotifyOut(
        discord_enabled=settings.discord_enabled,
        discord_webhook_set=bool(settings.discord_webhook),
        email_enabled=settings.email_enabled,
        email_to=settings.email_to,
        email_configured=is_configured(load_config(db)),
    )


@router.get("")
def get_notifications(_auth: AdminAuth, db: DbSession) -> NotifyOut:
    return _out(db)


@router.put("")
def put_notifications(body: NotifyIn, _auth: AdminAuth, db: DbSession) -> NotifyOut:
    current = load_settings(db)
    webhook = current.discord_webhook if body.discord_webhook is None else body.discord_webhook
    if body.discord_enabled and not webhook:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Save a webhook URL before enabling Discord alerts.",
        )
    if body.email_enabled and not body.email_to:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Enter a recipient before enabling email alerts.",
        )
    save_settings(
        db,
        discord_enabled=body.discord_enabled,
        email_enabled=body.email_enabled,
        email_to=body.email_to,
        discord_webhook=body.discord_webhook,
    )
    return _out(db)


@router.post("/test")
def test_channel(body: NotifyTestIn, _auth: AdminAuth, db: DbSession) -> NotifyTestOut:
    settings = load_settings(db)
    title = "EpicWing test"
    text = "This is a test alert from your EpicWing panel."
    if body.channel == "discord":
        if not settings.discord_webhook:
            return NotifyTestOut(ok=False, detail="No webhook saved yet.")
        ok, detail = send_discord(settings.discord_webhook, title, text)
    else:
        if not settings.email_to:
            return NotifyTestOut(ok=False, detail="No recipient saved yet.")
        ok, detail = send_email(db, settings.email_to, title, text)
    return NotifyTestOut(ok=ok, detail=detail)
