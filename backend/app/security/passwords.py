from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

# Checked when the user does not exist, so the response time stays the same.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    target = password_hash if password_hash is not None else _DUMMY_HASH
    try:
        valid = _hasher.verify(target, password)
    except (VerificationError, InvalidHashError):
        return False
    return valid and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
