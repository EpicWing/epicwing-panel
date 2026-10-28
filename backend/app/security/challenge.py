"""Kurzlebige Bestätigung zwischen Passwort und zweitem Faktor.

Zustandslos und mit dem Server-Geheimnis signiert. Sie enthält nur Benutzer, Ablaufzeit und einen
Teil des Passwort-Hashes. Ein Passwortwechsel macht offene Bestätigungen ungültig. Sie ersetzt
keinen Code: ohne gültigen, einmaligen Code entsteht keine Sitzung.
"""

import base64
import hashlib
import hmac
import time
import uuid

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User

CHALLENGE_TTL = 300


def _sign(payload: str) -> str:
    key = get_settings().epicwing_secret_key.encode()
    return hmac.new(key, b"2fa-challenge:" + payload.encode(), hashlib.sha256).hexdigest()


def _binding(user: User) -> str:
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:16]


def make_challenge(user: User) -> str:
    expires = int(time.time()) + CHALLENGE_TTL
    payload = f"{user.id}:{expires}:{_binding(user)}"
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{encoded}.{_sign(payload)}"


def read_challenge(db: Session, token: str) -> User | None:
    try:
        encoded, signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded.encode()).decode()
        user_id, expires, binding = payload.split(":")
        valid_until = int(expires)
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    if valid_until < time.time():
        return None
    user = db.get(User, user_uuid)
    if user is None or not hmac.compare_digest(binding, _binding(user)):
        return None
    return user
