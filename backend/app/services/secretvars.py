"""Secret egg variables (bot tokens and similar) are stored encrypted.

A stored value starts with "enc:" followed by a Fernet token. Values without the
prefix are older plain text values. They are still read as they are, until
`python -m app.encrypt_secrets` has encrypted them.
"""

from app.security.vault import decrypt_text, encrypt_text

PREFIX = "enc:"
PURPOSE = "server-variable"


def seal(value: str) -> str:
    """Encrypts a value for storage. An empty value stays empty."""
    if not value:
        return ""
    return PREFIX + encrypt_text(value, PURPOSE)


def unseal(stored: str) -> str:
    """Plain value of a stored one. Returns an empty string if it cannot be decrypted."""
    if not stored.startswith(PREFIX):
        return stored
    return decrypt_text(stored[len(PREFIX) :], PURPOSE) or ""
