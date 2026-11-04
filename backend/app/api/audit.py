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

# Console opens are too frequent and say nothing about changes.
HIDDEN_ACTIONS = ("server.console_open",)
EXPORT_LIMIT = 10_000
CSV_HEADER = ["time", "user", "action", "ip", "details"]

Group = Literal["power", "files", "backups", "ports", "server"]
# An entry with a dot at the end is a prefix, all others are exact actions.
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
    actor_id: str | None = None
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
        actor_id=str(entry.actor_id) if entry.actor_id else None,
        ip=entry.ip if show_ip else None,
        details=entry.details,
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _csv_cell(value: str) -> str:
    # Excel and similar tools would treat such cells as formulas.
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
        self.group_map: dict[str, tuple[str, ...]] = GROUPS

    def clauses(self) -> list[ColumnElement[bool]]:
        out: list[ColumnElement[bool]] = []
        if self.groups:
            patterns = [p for group in self.groups for p in self.group_map[group]]
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
            # Only the name part of the e-mail is searched, not the domain.
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
    # Only owners and administrators see the IP addresses of other users.
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


# Global activity for administrators

AdminGroup = Literal["security", "logins", "users", "keys", "nodes", "eggs", "servers"]
ADMIN_GROUPS: dict[str, tuple[str, ...]] = {
    "security": ("auth.login_failed", "auth.password_change_failed", "node.agent_auth_failed"),
    "logins": ("auth.",),
    "users": ("user.",),
    "keys": ("api_key.", "ssh_key."),
    "nodes": ("node.",),
    "eggs": ("egg.",),
    "servers": ("server.",),
}
ADMIN_CSV_HEADER = ["time", "user", "action", "target", "ip", "details"]

AuditAccess = Annotated[AuthContext, Depends(require(Permission.AUDIT_VIEW))]
DbSession = Annotated[Session, Depends(get_db)]


class AdminActivityFilter(ActivityFilter):
    def __init__(
        self,
        groups: Annotated[list[AdminGroup] | None, Query()] = None,
        since: date | None = None,
        until: date | None = None,
        q: Annotated[str | None, Query(max_length=100)] = None,
    ) -> None:
        super().__init__(None, since, until, q)
        self.groups = groups or []
        self.group_map = ADMIN_GROUPS


AdminFilter = Annotated[AdminActivityFilter, Depends()]


class AdminActivityItem(ActivityItem):
    target_type: str | None = None
    target_id: str | None = None


class AdminActivityPage(BaseModel):
    items: list[AdminActivityItem]
    has_more: bool


def _admin_items(db: Session, rows: list[AuditLog]) -> list[AdminActivityItem]:
    emails = _emails(db, rows)
    return [
        AdminActivityItem(
            **_item(row, emails.get(row.actor_id), True).model_dump(),
            target_type=row.target_type,
            target_id=row.target_id,
        )
        for row in rows
    ]


def _admin_query(flt: ActivityFilter):
    return (
        select(AuditLog)
        .where(AuditLog.action.not_in(HIDDEN_ACTIONS), *flt.clauses())
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )


@router.get("/events")
def admin_activity(
    _auth: AuditAccess,
    db: DbSession,
    flt: AdminFilter,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> AdminActivityPage:
    rows = list(db.scalars(_admin_query(flt).offset(offset).limit(limit + 1)))
    has_more = len(rows) > limit
    return AdminActivityPage(items=_admin_items(db, rows[:limit]), has_more=has_more)


@router.get("/events/export")
def export_admin_activity(
    request: Request,
    auth: AuditAccess,
    db: DbSession,
    flt: AdminFilter,
    fmt: Annotated[Literal["csv", "json"], Query(alias="format")] = "csv",
) -> Response:
    rows = list(db.scalars(_admin_query(flt).limit(EXPORT_LIMIT)))
    items = _admin_items(db, rows)

    if fmt == "json":
        body = json.dumps([i.model_dump(mode="json") for i in items], indent=2, ensure_ascii=False)
        media_type = "application/json"
    else:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(ADMIN_CSV_HEADER)
        for i in items:
            target = f"{i.target_type}:{i.target_id}" if i.target_type else ""
            details = json.dumps(i.details, ensure_ascii=False) if i.details else ""
            cells = (i.created_at.isoformat(), i.actor or "", i.action, target, i.ip or "", details)
            writer.writerow([_csv_cell(cell) for cell in cells])
        body = buffer.getvalue()
        media_type = "text/csv; charset=utf-8"

    audit.record(
        db,
        "audit.export",
        actor_id=auth.user.id,
        ip=audit.client_ip(request),
        details={"format": fmt, "rows": len(items)},
    )
    filename = f"audit-{secrets.token_hex(4)}.{fmt}"
    return Response(
        body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
