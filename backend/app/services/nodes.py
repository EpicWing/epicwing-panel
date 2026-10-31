import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Node, NodeCredential, NodeEnrollment
from app.security.sessions import hash_token

ENROLL_PREFIX = "epicwing_enroll_"
ENROLL_TTL = timedelta(hours=1)


def create_enrollment(db: Session, node: Node, created_by: uuid.UUID) -> tuple[str, NodeEnrollment]:
    """Creates a new token. The plain text is only returned here."""
    # Older unused tokens for this node become invalid.
    db.execute(
        delete(NodeEnrollment).where(
            NodeEnrollment.node_id == node.id, NodeEnrollment.used_at.is_(None)
        )
    )
    token = ENROLL_PREFIX + secrets.token_urlsafe(32)
    enrollment = NodeEnrollment(
        node_id=node.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + ENROLL_TTL,
        created_by=created_by,
    )
    db.add(enrollment)
    return token, enrollment


class EnrollmentError(Exception):
    """Token invalid, expired or used. Deliberately not more exact."""


class InvalidPublicKeyError(Exception):
    """The public key is not a valid Ed25519 key."""


def parse_public_key(value: str) -> tuple[str, str]:
    """Checks the key and returns (Base64, SHA-256 fingerprint)."""
    try:
        raw = base64.b64decode(value, validate=True)
        Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        raise InvalidPublicKeyError from exc
    return base64.b64encode(raw).decode(), hashlib.sha256(raw).hexdigest()


def enroll_agent(
    db: Session, token: str, public_key: str, agent_version: str | None
) -> tuple[Node, str]:
    """Redeems an enrollment token. The caller does the commit."""
    # Check the key first, so a typo does not use up the token.
    key_b64, fingerprint = parse_public_key(public_key)

    enrollment = db.scalar(
        select(NodeEnrollment)
        .where(NodeEnrollment.token_hash == hash_token(token))
        .with_for_update()
    )
    if enrollment is None or enrollment.used_at is not None:
        raise EnrollmentError
    expires_at = enrollment.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if expires_at <= now:
        raise EnrollmentError
    node = db.get(Node, enrollment.node_id)
    if node is None or node.status != "pending":
        raise EnrollmentError

    enrollment.used_at = now
    # Registered, but not connected yet.
    node.status = "offline"
    node.agent_version = agent_version
    db.add(NodeCredential(node_id=node.id, public_key=key_b64, fingerprint=fingerprint))
    return node, fingerprint


HEARTBEAT_TIMEOUT = timedelta(seconds=30)


def display_status(node: Node) -> str:
    """Waiting, online or offline. Online only counts with a fresh heartbeat."""
    if node.status == "pending":
        return "pending"
    beat = node.last_heartbeat_at
    if beat is None:
        return "offline"
    if beat.tzinfo is None:
        beat = beat.replace(tzinfo=UTC)
    return "online" if datetime.now(UTC) - beat <= HEARTBEAT_TIMEOUT else "offline"
