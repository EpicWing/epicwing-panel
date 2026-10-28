import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Node, NodeEnrollment
from app.security.sessions import hash_token

ENROLL_PREFIX = "epicwing_enroll_"
ENROLL_TTL = timedelta(hours=1)


def create_enrollment(
    db: Session, node: Node, created_by: uuid.UUID
) -> tuple[str, NodeEnrollment]:
    """Erzeugt einen neuen Token. Der Klartext wird nur hier zurückgegeben."""
    # Ältere unbenutzte Token für diesen Node werden ungültig.
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
