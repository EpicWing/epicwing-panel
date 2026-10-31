import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, UserSession

SESSION_COOKIE = "epicwing_session"
SESSION_MAX_AGE = timedelta(days=7)
SESSION_IDLE_TIMEOUT = timedelta(hours=12)
_LAST_SEEN_INTERVAL = timedelta(minutes=1)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class AuthContext:
    user: User
    session: UserSession


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    # SQLite liefert naive Zeitstempel (nur in den Tests), Postgres liefert aware.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(
    db: Session, user: User, ip: str | None, user_agent: str | None
) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    now = _utcnow()
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=secrets.token_urlsafe(32),
        ip=ip,
        user_agent=(user_agent or "")[:255] or None,
        last_seen_at=now,
        expires_at=now + SESSION_MAX_AGE,
    )
    db.add(session)
    db.commit()
    return token, session


def revoke_session(db: Session, session: UserSession) -> None:
    session.revoked_at = _utcnow()
    db.commit()


def revoke_token(db: Session, token: str) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.token_hash == hash_token(token), UserSession.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")


def get_auth(request: Request, db: Annotated[Session, Depends(get_db)]) -> AuthContext:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _unauthorized()

    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    now = _utcnow()
    if (
        session is None
        or session.revoked_at is not None
        or _aware(session.expires_at) <= now
        or now - _aware(session.last_seen_at) > SESSION_IDLE_TIMEOUT
        or session.user.disabled_at is not None
    ):
        raise _unauthorized()

    # Schreibende Requests brauchen das CSRF-Token der Session.
    if request.method not in _SAFE_METHODS:
        sent = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(sent.encode(), session.csrf_token.encode()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token is missing or invalid.")

    if now - _aware(session.last_seen_at) > _LAST_SEEN_INTERVAL:
        session.last_seen_at = now
        db.commit()

    return AuthContext(user=session.user, session=session)


CurrentAuth = Annotated[AuthContext, Depends(get_auth)]


def revoke_other_sessions(db: Session, keep: UserSession) -> None:
    """Ends all sessions of the user except the one given."""
    db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == keep.user_id,
            UserSession.id != keep.id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=_utcnow())
    )
