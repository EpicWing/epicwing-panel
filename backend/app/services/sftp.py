"""SFTP login: does an SSH key belong to an account that may use the server?"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Server, SshKey, User
from app.security.ratelimit import sftp_reject_limiter
from app.security.server_access import ServerPermission, effective_permissions
from app.services import audit

_HEX = set("0123456789abcdef-")


@dataclass(frozen=True)
class SftpGrant:
    server_id: uuid.UUID
    write: bool


def _check(db: Session, node_id: uuid.UUID, fingerprint: str, server_ref: str) -> SftpGrant | None:
    """None means refused, with no reason: the agent does not learn why."""
    ref = server_ref.strip().lower()
    if not 4 <= len(ref) <= 36 or not set(ref) <= _HEX:
        return None
    key = db.scalar(select(SshKey).where(SshKey.fingerprint == fingerprint))
    if key is None:
        return None
    user = db.get(User, key.user_id)
    if user is None or user.disabled_at is not None:
        return None

    # Load only the IDs, not whole server rows: this runs for every login and
    # once a minute for every open connection.
    ids = [
        sid
        for sid in db.scalars(select(Server.id).where(Server.node_id == node_id))
        if str(sid).startswith(ref)
    ]
    # A short ID must be unique, otherwise nobody gets access.
    if len(ids) != 1:
        return None
    server = db.get(Server, ids[0])
    if server is None:
        return None
    granted = effective_permissions(db, user, [server])[server.id]
    if ServerPermission.FILES_READ.value not in granted:
        return None

    return SftpGrant(server.id, ServerPermission.FILES_WRITE.value in granted)


def authorize(
    db: Session, node_id: uuid.UUID, fingerprint: str, server_ref: str
) -> SftpGrant | None:
    """None means refused, with no reason: the agent does not learn why."""
    grant = _check(db, node_id, fingerprint, server_ref)
    reject_key = f"{node_id}|{fingerprint[:64]}"
    # Throttle audit entries for rejected logins, otherwise the audit log can be flooded
    if grant is None and sftp_reject_limiter.retry_after(reject_key) == 0:
        sftp_reject_limiter.add_failure(reject_key)
        audit.record(
            db,
            "sftp.login_rejected",
            target_type="node",
            target_id=str(node_id),
            details={"fingerprint": fingerprint[:64]},
        )
    return grant


def record_login(db: Session, node_id: uuid.UUID, fingerprint: str, server_id: str) -> None:
    """The agent reports a finished login: audit entry and last used time."""
    try:
        sid = uuid.UUID(server_id)
    except ValueError:
        return
    key = db.scalar(select(SshKey).where(SshKey.fingerprint == fingerprint))
    server = db.get(Server, sid)
    if key is None or server is None or server.node_id != node_id:
        return
    key.last_used_at = datetime.now(UTC)
    db.commit()
    audit.record(
        db,
        "sftp.login",
        actor_id=key.user_id,
        target_type="server",
        target_id=str(server.id),
        details={"fingerprint": fingerprint},
    )
