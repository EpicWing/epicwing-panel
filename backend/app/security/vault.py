"""Encryption of small secrets (Fernet, key from HKDF per purpose)."""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import get_settings


def _fernet(purpose: str) -> Fernet:
    raw = get_settings().epicwing_encryption_key.encode()
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"epicwing-{purpose}-v1".encode(),
    ).derive(raw)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_text(plain: str, purpose: str) -> str:
    return _fernet(purpose).encrypt(plain.encode()).decode()


def decrypt_text(token: str, purpose: str) -> str | None:
    try:
        return _fernet(purpose).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
