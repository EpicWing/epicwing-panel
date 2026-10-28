import csv
import io
import json
import secrets
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import ColumnElement, String, cast, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, User
from app.schemas.audit import AuditLogOut
from app.security.permissions import Permission, require
from app.security.server_access import ServerAccess, ServerPermission, server_access
from app.security.sessions import AuthContext
from app.services import audit

router = APIRouter(prefix="/audit-logs", tags=["audit"])
server_router = APIRouter(prefix="/servers", tags=["audit"])

# Konsole-Öffnungen sind zu häufig und sagen nichts über Änderungen aus.
HIDDEN_ACTIONS = ("server.console_open",)
EXPORT_LIMIT = 10_000
CSV_HEADER = ["time", "user", "action", "ip", "details"]

Group = Literal["power", "files", "backups", "ports", "server"]
# Ein Eintrag mit Punkt am Ende ist ein Präfix, alle anderen sind exakte Aktionen.
GROUPS: dict[str, tuple[str, ...]] = {
    "power": ("server.power",),
    "files": ("server.file.",),
    "backups": ("server.backup.",),
    "ports": ("server.allocation.",),
    "server": ("server.create", "server.update", "server.install", "server.delete"),
}

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


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _csv_cell(value: str) -> str:
    # Excel und Co. würden solche Zellen als Formel auswerten.
    if value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


class ActivityFilter:
    def __init__(
        self,
        groups: Annotated[list[Group] | None, Query()] = None,
        since: date | None = None,
        until: date | None = None,
        q: Annotated[str | None, Query(max_length=100)] = None,
    ) -> None:
        if since and until and since > until:
            raise HTTPException(422, "The start date must not be after the end date.")
        self.groups = groups or []
        self.since = since
        self.until = until
        self.q = (q or "").strip()

    def clauses(self) -> list[ColumnElement[bool]]:
        out: list[ColumnElement[bool]] = []
        if self.groups:
            patterns = [p for group in self.groups for p in GROUPS[group]]
            out.append(
                or_(
                    *[
                        AuditLog.action.startswith(p, autoescape=True)
                        if p.endswith(".")
                        else AuditLog.action == p
                        for p in patterns
                    ]
                )
            )
        if self.since:
            out.append(AuditLog.created_at >= datetime.combine(self.since, time.min, tzinfo=UTC))
        if self.until:
            end = datetime.combine(self.until + timedelta(days=1), time.min, tzinfo=UTC)
            out.append(AuditLog.created_at < end)
        if self.q:
            like = f"%{_escape_like(self.q)}%"
            # Gesucht wird nur im Namensteil der E-Mail, nicht in der Domain.
            by_actor = select(User.id).where(
                User.email.ilike(f"%{_escape_like(self.q)}%@%", escape="\\")
            )
            out.append(
                or_(
                    AuditLog.actor_id.in_(by_actor),
                    AuditLog.action.ilike(like, escape="\\"),
                    cast(AuditLog.details, String).ilike(like, escape="\\"),
                )
            )
        return out


def _base(access: ServerAccess) -> list[ColumnElement[bool]]:
    return [
        AuditLog.target_type == "server",
        AuditLog.target_id == str(access.server.id),
        AuditLog.action.not_in(HIDDEN_ACTIONS),
    ]


def _emails(db: Session, rows: list[AuditLog]) -> dict[uuid.UUID, str]:
    ids = {row.actor_id for row in rows if row.actor_id is not None}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.email).where(User.id.in_(ids))).all())


def _show_ip(access: ServerAccess) -> bool:
    # IP-Adressen anderer Nutzer sehen nur Besitzer und Administratoren.
    return access.is_admin or access.server.owner_id == access.user.id


@server_router.get("/{server_id}/activity")
def server_activity(
    access: ActivityAccess,
    db: Annotated[Session, Depends(get_db)],
    flt: Annotated[ActivityFilter, Depends()],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> ActivityPage:
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(*_base(access), *flt.clauses())
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    emails = _emails(db, rows)
    show_ip = _show_ip(access)
    items = [_item(row, emails.get(row.actor_id), show_ip) for row in rows]
    return ActivityPage(items=items, has_more=has_more)


@server_router.get("/{server_id}/activity/export")
def export_activity(
    request: Request,
    access: ActivityAccess,
    db: Annotated[Session, Depends(get_db)],
    flt: Annotated[ActivityFilter, Depends()],
    fmt: Annotated[Literal["csv", "json"], Query(alias="format")] = "csv",
) -> Response:
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(*_base(access), *flt.clauses())
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(EXPORT_LIMIT)
        )
    )
    emails = _emails(db, rows)
    show_ip = _show_ip(access)
    items = [_item(row, emails.get(row.actor_id), show_ip) for row in rows]

    if fmt == "json":
        body = json.dumps([i.model_dump(mode="json") for i in items], indent=2, ensure_ascii=False)
        media_type = "application/json"
    else:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(CSV_HEADER)
        for i in items:
            details = json.dumps(i.details, ensure_ascii=False) if i.details else ""
            cells = (i.created_at.isoformat(), i.actor or "", i.action, i.ip or "", details)
            writer.writerow([_csv_cell(cell) for cell in cells])
        body = buffer.getvalue()
        media_type = "text/csv; charset=utf-8"

    filters: dict[str, object] = {}
    if flt.groups:
        filters["groups"] = flt.groups
    if flt.since:
        filters["since"] = flt.since.isoformat()
    if flt.until:
        filters["until"] = flt.until.isoformat()
    if flt.q:
        filters["q"] = flt.q

    details: dict[str, object] = {"name": access.server.name, "format": fmt, "rows": len(items)}
    if filters:
        details["filters"] = filters

    audit.record(
        db,
        "server.activity.export",
        actor_id=access.user.id,
        target_type="server",
        target_id=str(access.server.id),
        ip=audit.client_ip(request),
        details=details,
    )

    filename = f"activity-{secrets.token_hex(4)}.{fmt}"
    return Response(
        body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
