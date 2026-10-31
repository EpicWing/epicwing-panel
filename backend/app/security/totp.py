"""Two-factor logic (TOTP) and recovery codes.

- Das Geheimnis liegt verschlüsselt (Fernet) in der Datenbank. Der Schlüssel wird per HKDF
  aus EPICWING_ENCRYPTION_KEY abgeleitet.
- A code works only once: the last used time step is stored atomically.
- Recovery codes exist only as a SHA-256 hash and can be used once.
"""

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import UTC, datetime

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RecoveryCode, User

ISSUER = "EpicWing"
TOTP_STEP = 30
TOTP_WINDOW = 1
RECOVERY_CODE_COUNT = 10
# Ohne leicht verwechselbare Zeichen (I, O, 0, 1): genau 32 Zeichen, also 5 Bit pro Zeichen.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE = re.compile(r"[0-9]{6}")


def _fernet() -> Fernet:
    raw = get_settings().epicwing_encryption_key.encode()
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"epicwing-totp-v1").derive(
        raw
    )
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def is_enabled(user: User) -> bool:
    return user.totp_secret is not None and user.totp_enabled_at is not None


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret, interval=TOTP_STEP).provisioning_uri(name=email, issuer_name=ISSUER)


def begin_enrollment(db: Session, user: User) -> str:
    """Creates a new secret. 2FA only becomes active with activate()."""
    if is_enabled(user):
        raise ValueError("2FA is already enabled")
    secret = pyotp.random_base32()
    user.totp_secret = encrypt_secret(secret)
    user.totp_enabled_at = None
    user.totp_last_step = None
    db.commit()
    return secret


def verify_code(db: Session, user: User, code: str, now: float | None = None) -> bool:
    """Checks a 6-digit code (±1 time step) and uses it up."""
    candidate = code.replace(" ", "")
    if not _CODE.fullmatch(candidate) or not user.totp_secret:
        return False
    secret = decrypt_secret(user.totp_secret)
    if secret is None:
        return False

    current = int((time.time() if now is None else now) // TOTP_STEP)
    generator = pyotp.TOTP(secret, interval=TOTP_STEP)
    matched = None
    for step in range(current - TOTP_WINDOW, current + TOTP_WINDOW + 1):
        if hmac.compare_digest(generator.at(step * TOTP_STEP), candidate):
            matched = step
    if matched is None:
        return False

    # Atomic: only a newer time step than the last used one is accepted.
    result = db.execute(
        update(User)
        .where(
            User.id == user.id,
            or_(User.totp_last_step.is_(None), User.totp_last_step < matched),
        )
        .values(totp_last_step=matched)
    )
    db.commit()
    db.refresh(user)
    return result.rowcount == 1


def _hash_recovery(code: str) -> str:
    normalized = code.replace("-", "").replace(" ", "").upper()
    return hashlib.sha256(normalized.encode()).hexdigest()


def generate_recovery_codes(db: Session, user: User) -> list[str]:
    """Ersetzt alle Wiederherstellungscodes. Die Klartext-Codes gibt es nur hier einmalig."""
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(12))
        code = f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"
        codes.append(code)
        db.add(RecoveryCode(user_id=user.id, code_hash=_hash_recovery(code)))
    db.commit()
    return codes


def consume_recovery_code(db: Session, user: User, code: str) -> bool:
    result = db.execute(
        update(RecoveryCode)
        .where(
            RecoveryCode.user_id == user.id,
            RecoveryCode.code_hash == _hash_recovery(code),
            RecoveryCode.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
    )
    db.commit()
    return result.rowcount == 1


def remaining_recovery_codes(db: Session, user: User) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(RecoveryCode)
            .where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
        )
        or 0
    )


def activate(db: Session, user: User) -> list[str]:
    """Turns 2FA on (after a confirmed code) and returns the recovery codes."""
    user.totp_enabled_at = datetime.now(UTC)
    db.commit()
    return generate_recovery_codes(db, user)


def disable(db: Session, user: User) -> None:
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    user.totp_secret = None
    user.totp_enabled_at = None
    user.totp_last_step = None
    db.commit()
