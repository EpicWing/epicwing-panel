import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

# Checked when the user does not exist, so the response time stays the same.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


# Pterodactyl and Pelican store bcrypt hashes. They are accepted at login and
# replaced with argon2 right after, because needs_rehash() says so.
_BCRYPT = ("$2y$", "$2b$", "$2a$")


def _is_bcrypt(password_hash: str) -> bool:
    return password_hash.startswith(_BCRYPT)


def _verify_bcrypt(password_hash: str, password: str) -> bool:
    # Laravel writes $2y$, the bcrypt library expects $2b$. It is the same algorithm.
    try:
        return bcrypt.checkpw(password.encode(), ("$2b$" + password_hash[4:]).encode())
    except ValueError:
        return False


def verify_password(password_hash: str | None, password: str) -> bool:
    if password_hash is not None and _is_bcrypt(password_hash):
        return _verify_bcrypt(password_hash, password)
    target = password_hash if password_hash is not None else _DUMMY_HASH
    try:
        valid = _hasher.verify(target, password)
    except (VerificationError, InvalidHashError):
        return False
    return valid and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _is_bcrypt(password_hash) or _hasher.check_needs_rehash(password_hash)
