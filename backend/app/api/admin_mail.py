"""Admin: E-Mail-Einstellungen (Resend oder SMTP) und Test-Mail."""

from email.utils import parseaddr
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.security.permissions import AdminAuth
from app.services.mail import (
    is_configured,
    load_config,
    render_for,
    save_config,
    send_mail,
)

router = APIRouter(prefix="/admin/mail", tags=["admin"])
DbSession = Annotated[Session, Depends(get_db)]


def _address(value: str) -> str:
    value = value.strip()
    if "\r" in value or "\n" in value:
        raise ValueError("Line breaks are not allowed")
    if "@" not in parseaddr(value)[1]:
        raise ValueError("Enter a valid email address")
    return value


def _single_line(value: str) -> str:
    value = value.strip()
    if "\r" in value or "\n" in value:
        raise ValueError("Line breaks are not allowed")
    return value


class MailSettingsOut(BaseModel):
    provider: Literal["resend", "smtp"]
    sender: str
    reply_to: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_security: Literal["starttls", "ssl", "none"]
    resend_api_key_set: bool
    smtp_password_set: bool
    configured: bool


class MailSettingsIn(BaseModel):
    provider: Literal["resend", "smtp"]
    sender: str = Field(min_length=3, max_length=200)
    reply_to: str = Field("", max_length=200)
    smtp_host: str = Field("", max_length=200)
    smtp_port: int = Field(587, ge=1, le=65535)
    smtp_user: str = Field("", max_length=200)
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    resend_api_key: str | None = Field(None, max_length=200)
    smtp_password: str | None = Field(None, max_length=200)

    @field_validator("sender")
    @classmethod
    def _check_sender(cls, value: str) -> str:
        return _address(value)

    @field_validator("reply_to")
    @classmethod
    def _check_reply_to(cls, value: str) -> str:
        return _address(value) if value.strip() else ""

    @field_validator("smtp_host", "smtp_user")
    @classmethod
    def _check_plain(cls, value: str) -> str:
        return _single_line(value)

    @field_validator("resend_api_key")
    @classmethod
    def _check_key(cls, value: str | None) -> str | None:
        return None if value is None else _single_line(value)


class MailTestIn(BaseModel):
    to: str = Field(min_length=3, max_length=200)

    @field_validator("to")
    @classmethod
    def _check_to(cls, value: str) -> str:
        return _address(value)


class MailTestOut(BaseModel):
    ok: bool
    detail: str


def _out(db: Session) -> MailSettingsOut:
    config = load_config(db)
    return MailSettingsOut(
        provider=config.provider,  # type: ignore[arg-type]
        sender=config.sender,
        reply_to=config.reply_to,
        smtp_host=config.smtp_host,
        smtp_port=config.smtp_port,
        smtp_user=config.smtp_user,
        smtp_security=config.smtp_security,  # type: ignore[arg-type]
        resend_api_key_set=bool(config.resend_api_key),
        smtp_password_set=bool(config.smtp_password),
        configured=is_configured(config),
    )


@router.get("")
def get_mail(_auth: AdminAuth, db: DbSession) -> MailSettingsOut:
    return _out(db)


@router.put("")
def put_mail(body: MailSettingsIn, _auth: AdminAuth, db: DbSession) -> MailSettingsOut:
    save_config(db, body.model_dump())
    return _out(db)


@router.post("/test")
def send_test(body: MailTestIn, _auth: AdminAuth, db: DbSession) -> MailTestOut:
    config = load_config(db)
    html, text = render_for(
        config,
        "Mail delivery works",
        [
            "This is a test message from your EpicWing panel.",
            "If you can read this, the panel can send emails with your settings.",
        ],
    )
    ok, detail = send_mail(body.to, "EpicWing test email", html, text, config)
    return MailTestOut(ok=ok, detail=detail)
