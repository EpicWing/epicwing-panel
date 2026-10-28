import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session,
    action: str,
    *,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    details: dict | None = None,
) -> None:
    via_key = db.info.get("api_key")
    if via_key:
        details = {**(details or {}), "via_api_key": via_key}
    db.add(
        AuditLog(
            action=action,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            details=details,
        )
    )
    db.commit()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
