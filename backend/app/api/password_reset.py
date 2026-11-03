"""Password reset by e-mail: request a link, then set a new password with it."""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import PasswordResetToken, User, UserSession
from app.security.passwords import hash_password
from app.security.ratelimit import (
    login_email_limiter,
    reset_confirm_ip_limiter,
    reset_request_email_limiter,
    reset_request_ip_limiter,
)
from app.services import audit
from app.services import mail as mail_service

log = logging.getLogger("epicwing.password_reset")
router = APIRouter(prefix="/auth/password-reset", tags=["auth"])
DbSession = Annotated[Session, Depends(get_db)]

TOKEN_LIFETIME = timedelta(minutes=30)
# The same answer for known and unknown addresses, so nobody can probe for accounts.
ACCEPTED = {
    "detail": "If an account with this address exists, an email with a link is on its way."
}


class ResetRequest(BaseModel):
    email: str = Field(max_length=320)


class ResetConfirm(BaseModel):
    token: str = Field(min_length=16, max_length=200)
    new_password: str = Field(min_length=8, max_length=1024)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _too_many(wait: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many attempts. Please try again later.",
        headers={"Retry-After": str(wait)},
    )


def _mail_config(db: Session):
    """The mail settings, or None if a reset mail cannot be sent."""
    # The link is built from the fixed public URL, never from the Host header.
    if not get_settings().public_origin:
        return None
    config = mail_service.load_config(db)
    return config if mail_service.is_configured(config) else None


def _send_mail(config, to: str, link: str) -> None:
    page, plain = mail_service.render_for(
        config,
        "Reset your password",
        [
            "Someone asked to reset the password of your EpicWing account.",
            "The link works for 30 minutes and only once. If this was not you, "
            "ignore this email. Your password stays the same.",
            f"If the button does not work, copy this link: {link}",
        ],
        ("Choose a new password", link),
    )
    ok, info = mail_service.send_mail(to, "Reset your EpicWing password", page, plain, config)
    if not ok:
        log.warning("Password reset mail failed: %s", info)


@router.get("/available")
def available(db: DbSession) -> dict[str, bool]:
    return {"available": _mail_config(db) is not None}


@router.post("/request", status_code=status.HTTP_202_ACCEPTED)
def request_reset(
    body: ResetRequest,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
) -> dict[str, str]:
    config = _mail_config(db)
    if config is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Password reset is not available.")

    ip = _client_ip(request)
    wait = reset_request_ip_limiter.retry_after(ip)
    if wait:
        raise _too_many(wait)
    reset_request_ip_limiter.add_failure(ip)

    email = body.email.strip().lower()
    if reset_request_email_limiter.retry_after(email):
        # Silent: the answer must not show that this address was asked for before.
        return ACCEPTED
    reset_request_email_limiter.add_failure(email)

    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.disabled_at is not None:
        return ACCEPTED

    now = datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    # Old links stop working, expired rows are cleaned up.
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    db.execute(
        delete(PasswordResetToken).where(PasswordResetToken.expires_at < now - timedelta(days=1))
    )
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash(token),
            expires_at=now + TOKEN_LIFETIME,
        )
    )
    db.commit()
    audit.record(db, "auth.password_reset_requested", actor_id=user.id, ip=ip)
    db.commit()

    # The token sits behind the # so it never reaches server logs or Referer headers.
    link = f"{get_settings().public_origin}/reset-password#token={token}"
    # Sent after the response, so the answer time does not depend on the account.
    background.add_task(_send_mail, config, user.email, link)
    return ACCEPTED


@router.post("/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_reset(body: ResetConfirm, request: Request, db: DbSession) -> None:
    ip = _client_ip(request)
    wait = reset_confirm_ip_limiter.retry_after(ip)
    if wait:
        raise _too_many(wait)

    now = datetime.now(UTC)
    row = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == _hash(body.token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )
    user = db.get(User, row.user_id) if row else None
    if row is None or user is None or user.disabled_at is not None:
        reset_confirm_ip_limiter.add_failure(ip)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired.")

    user.password_hash = hash_password(body.new_password)
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    # Every session of the account ends. Two-factor stays required at the next login.
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.commit()
    # Someone who was locked out by failed logins can sign in again.
    login_email_limiter.reset(user.email.lower())
    # The password and the token never go into the audit log.
    audit.record(db, "auth.password_reset", actor_id=user.id, ip=ip)
    db.commit()
