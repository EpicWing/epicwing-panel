import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, User
from app.schemas.audit import AuditLogOut
from app.security.permissions import Permission, require
from app.security.server_access import ServerAccess, ServerPermission, server_access
from app.security.sessions import AuthContext

router = APIRouter(prefix="/audit-logs", tags=["audit"])
server_router = APIRouter(prefix="/servers", tags=["audit"])

ActivityAccess = Annotated[ServerAccess, Depends(server_access(ServerPermission.SETTINGS_VIEW))]


@router.get("")
def list_audit_logs(
    _auth: Annotated[AuthContext, Depends(require(Permission.AUDIT_VIEW))],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditLogOut]:
    entries = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    return [AuditLogOut.model_validate(e) for e in entries]


class ActivityItem(BaseModel):
    id: uuid.UUID
    created_at: datetime
    action: str
    actor: str | None
    ip: str | None
    details: dict | None


class ActivityPage(BaseModel):
    items: list[ActivityItem]
    has_more: bool


def _item(entry: AuditLog, actor: str | None, show_ip: bool) -> ActivityItem:
    return ActivityItem(
        id=entry.id,
        created_at=entry.created_at,
        action=entry.action,
        actor=actor,
        ip=entry.ip if show_ip else None,
        details=entry.details,
    )


@server_router.get("/{server_id}/activity")
def server_activity(
    access: ActivityAccess,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> ActivityPage:
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.target_type == "server", AuditLog.target_id == str(access.server.id))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    actor_ids = {row.actor_id for row in rows if row.actor_id is not None}
    emails: dict[uuid.UUID, str] = {}
    if actor_ids:
        emails = dict(db.execute(select(User.id, User.email).where(User.id.in_(actor_ids))).all())
    # IP-Adressen anderer Nutzer sehen nur Besitzer und Administratoren.
    show_ip = access.is_admin or access.server.owner_id == access.user.id
    items = [_item(row, emails.get(row.actor_id), show_ip) for row in rows]
    return ActivityPage(items=items, has_more=has_more)
