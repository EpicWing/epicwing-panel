"""Check public SSH keys and compute the fingerprint."""

import base64
import binascii
import hashlib

ALLOWED_TYPES = {
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "ssh-rsa",
}
MIN_RSA_BITS = 2048


def _read_string(blob: bytes, pos: int) -> tuple[bytes, int]:
    if pos + 4 > len(blob):
        raise ValueError("The key is truncated.")
    length = int.from_bytes(blob[pos : pos + 4], "big")
    end = pos + 4 + length
    if end > len(blob):
        raise ValueError("The key is truncated.")
    return blob[pos + 4 : end], end


def parse_public_key(text: str) -> tuple[str, str, str]:
    """Returns type, normalized key (without comment) and fingerprint."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("Paste exactly one public key.")
    parts = lines[0].split()
    if len(parts) < 2:
        raise ValueError("This does not look like a public key.")
    key_type, b64 = parts[0], parts[1]
    if key_type not in ALLOWED_TYPES:
        raise ValueError("Unsupported key type. Use ed25519, ecdsa or RSA.")
    try:
        blob = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("The key is not valid base64.") from None

    inner_type, pos = _read_string(blob, 0)
    if inner_type.decode("ascii", "ignore") != key_type:
        raise ValueError("The key type does not match the key data.")
    if key_type == "ssh-ed25519":
        data, _ = _read_string(blob, pos)
        if len(data) != 32:
            raise ValueError("The ed25519 key has the wrong length.")
    elif key_type == "ssh-rsa":
        _, pos = _read_string(blob, pos)
        modulus, _ = _read_string(blob, pos)
        if int.from_bytes(modulus, "big").bit_length() < MIN_RSA_BITS:
            raise ValueError(f"RSA keys need at least {MIN_RSA_BITS} bits.")
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return key_type, f"{key_type} {b64}", fingerprint
