"""Anmeldung per API Key (Authorization: Bearer ewk_...).

Ein Key gilt nur an Endpunkten, die ServerAuth benutzen. Konto, 2FA, Keys, Benutzer und der
Admin-Bereich bleiben an die Cookie-Session gebunden.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ApiKey, User
from app.security.sessions import AuthContext, get_auth, hash_token

KEY_PREFIX = "ewk_"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_LAST_USED_INTERVAL = timedelta(minutes=1)


@dataclass
class KeyContext:
    user: User
    session: None
    key: ApiKey


def new_key() -> tuple[str, str, str]:
    """Token, Kennung für die Liste und Hash für die Datenbank."""
    token = KEY_PREFIX + secrets.token_urlsafe(32)
    return token, token[:12], hash_token(token)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _bearer_key(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    value = value.strip()
    if scheme.lower() == "bearer" and value.startswith(KEY_PREFIX):
        return value
    return None


def _invalid() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key.")


def get_server_auth(
    request: Request, db: Annotated[Session, Depends(get_db)]
) -> AuthContext | KeyContext:
    token = _bearer_key(request)
    if token is None:
        # Ohne Key gilt wie bisher die Cookie-Session samt CSRF-Prüfung.
        return get_auth(request, db)

    key = db.scalar(select(ApiKey).where(ApiKey.token_hash == hash_token(token)))
    now = datetime.now(UTC)
    if key is None or (key.expires_at is not None and _aware(key.expires_at) <= now):
        raise _invalid()
    user = db.get(User, key.user_id)
    if user is None or user.disabled_at is not None:
        raise _invalid()
    # Kein Browser-Cookie im Spiel, deshalb braucht ein Key kein CSRF-Token.
    if key.read_only and request.method not in _SAFE_METHODS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This API key is read-only.")

    if key.last_used_at is None or now - _aware(key.last_used_at) > _LAST_USED_INTERVAL:
        key.last_used_at = now
        db.commit()
    return KeyContext(user=user, session=None, key=key)


ServerAuth = Annotated[AuthContext | KeyContext, Depends(get_server_auth)]
