"""Access control of a server: who besides the owner may do what.

Rules enforced here:
- access.view is for viewing, access.manage is for changing.
- Admins and the owner can give out any permission.
- Everyone else can only give permissions they have themselves, and can only
  change members whose permissions are fully included in their own.
- Nobody changes their own permissions. Removing your own access is allowed.
- server.view is always implied for members and is not stored.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.models.server import ServerMember, ServerMemberPermission
from app.security.server_access import (
    ALL_SERVER_PERMISSIONS,
    ServerAccess,
    ServerPermission,
    server_access,
)
from app.services import audit

router = APIRouter(prefix="/servers/{server_id}/access", tags=["access"])

AccessView = Annotated[ServerAccess, Depends(server_access(ServerPermission.ACCESS_VIEW))]
AccessManage = Annotated[ServerAccess, Depends(server_access(ServerPermission.ACCESS_MANAGE))]
DbSession = Annotated[Session, Depends(get_db)]

IMPLICIT = {ServerPermission.VIEW.value}
GRANTABLE = ALL_SERVER_PERMISSIONS - IMPLICIT


def _clean(values: list[str]) -> list[str]:
    unknown = sorted(set(values) - ALL_SERVER_PERMISSIONS)
    if unknown:
        raise ValueError("Unknown permission: " + ", ".join(unknown))
    return sorted(set(values) - IMPLICIT)


class _WithPermissions(BaseModel):
    permissions: list[str] = Field(max_length=64)

    @field_validator("permissions")
    @classmethod
    def _valid(cls, values: list[str]) -> list[str]:
        return _clean(values)


class MemberCreate(_WithPermissions):
    email: str = Field(min_length=3, max_length=254)


class MemberUpdate(_WithPermissions):
    pass


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    permissions: list[str]
    created_at: datetime


class AccessList(BaseModel):
    owner_id: uuid.UUID | None
    members: list[MemberOut]
    available_permissions: list[str]
    can_manage: bool


def _unrestricted(access: ServerAccess) -> bool:
    return access.is_admin or access.server.owner_id == access.user.id


def _forbidden(message: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, message)


def _guard(
    access: ServerAccess,
    target_user_id: uuid.UUID,
    requested: set[str],
    current: set[str],
    allow_self: bool = False,
) -> None:
    """Stops anyone from giving themselves more permissions through these routes."""
    if _unrestricted(access):
        return
    if target_user_id == access.user.id and not allow_self:
        raise _forbidden("You cannot change your own access.")
    if not requested <= access.permissions:
        raise _forbidden("You can only grant permissions you hold yourself.")
    if not current <= access.permissions:
        raise _forbidden("You cannot change a member who has permissions you do not hold.")


def _stored(db: Session, member_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
    result: dict[uuid.UUID, set[str]] = {member_id: set() for member_id in member_ids}
    if member_ids:
        rows = db.execute(
            select(ServerMemberPermission.member_id, ServerMemberPermission.permission).where(
                ServerMemberPermission.member_id.in_(member_ids)
            )
        )
        for member_id, permission in rows:
            if permission in GRANTABLE:
                result[member_id].add(permission)
    return result


def _load(db: Session, server_id: uuid.UUID, member_id: uuid.UUID) -> ServerMember:
    member = db.scalar(
        select(ServerMember).where(
            ServerMember.id == member_id, ServerMember.server_id == server_id
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.")
    return member


def _out(member: ServerMember, user: User, permissions: set[str]) -> MemberOut:
    return MemberOut(
        id=member.id,
        user_id=user.id,
        email=user.email,
        permissions=sorted(permissions),
        created_at=member.created_at,
    )


def _record(
    db: Session, request: Request, access: ServerAccess, action: str, **details: Any
) -> None:
    audit.record(
        db,
        action,
        actor_id=access.user.id,
        ip=audit.client_ip(request),
        details={"server_id": str(access.server.id), **details},
    )


@router.get("")
def list_members(access: AccessView, db: DbSession) -> AccessList:
    rows = db.execute(
        select(ServerMember, User)
        .join(User, User.id == ServerMember.user_id)
        .where(ServerMember.server_id == access.server.id)
        .order_by(ServerMember.created_at)
    ).all()
    stored = _stored(db, [member.id for member, _ in rows])
    available = GRANTABLE if _unrestricted(access) else GRANTABLE & access.permissions
    return AccessList(
        owner_id=access.server.owner_id,
        members=[_out(member, user, stored[member.id]) for member, user in rows],
        available_permissions=sorted(available),
        can_manage=access.has(ServerPermission.ACCESS_MANAGE),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def add_member(
    body: MemberCreate, request: Request, access: AccessManage, db: DbSession
) -> MemberOut:
    server = access.server
    target = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    taken = (
        target is not None
        and target.disabled_at is None
        and target.id != server.owner_id
        and db.scalar(
            select(ServerMember.id).where(
                ServerMember.server_id == server.id, ServerMember.user_id == target.id
            )
        )
        is not None
    )
    if target is None or target.disabled_at is not None or target.id == server.owner_id or taken:
        # Same answer in all cases, so nobody can tell "does not exist", "owner"
        # and "already a member" apart and list e-mail addresses that way.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This user already has access or the user does not exist."
        )

    requested = set(body.permissions)
    _guard(access, target.id, requested, set())

    member = ServerMember(server_id=server.id, user_id=target.id)
    db.add(member)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This user already has access.") from None
    db.add_all(ServerMemberPermission(member_id=member.id, permission=p) for p in sorted(requested))
    _record(
        db,
        request,
        access,
        "server.access.add",
        member_user_id=str(target.id),
        permissions=sorted(requested),
    )
    db.commit()
    return _out(member, target, requested)


@router.put("/{member_id}")
def update_member(
    member_id: uuid.UUID,
    body: MemberUpdate,
    request: Request,
    access: AccessManage,
    db: DbSession,
) -> MemberOut:
    member = _load(db, access.server.id, member_id)
    current = _stored(db, [member.id])[member.id]
    requested = set(body.permissions)
    _guard(access, member.user_id, requested, current)

    db.execute(delete(ServerMemberPermission).where(ServerMemberPermission.member_id == member.id))
    db.add_all(ServerMemberPermission(member_id=member.id, permission=p) for p in sorted(requested))
    _record(
        db,
        request,
        access,
        "server.access.update",
        member_user_id=str(member.user_id),
        added=sorted(requested - current),
        removed=sorted(current - requested),
    )
    db.commit()
    user = db.get(User, member.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return _out(member, user, requested)


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    member_id: uuid.UUID, request: Request, access: AccessManage, db: DbSession
) -> None:
    member = _load(db, access.server.id, member_id)
    current = _stored(db, [member.id])[member.id]
    _guard(access, member.user_id, set(), current, allow_self=True)
    # Delete explicitly: not every database enforces ON DELETE CASCADE.
    db.execute(delete(ServerMemberPermission).where(ServerMemberPermission.member_id == member.id))
    db.delete(member)
    _record(
        db,
        request,
        access,
        "server.access.remove",
        member_user_id=str(member.user_id),
        permissions=sorted(current),
    )
    db.commit()


CANDIDATE_MIN_QUERY = 0  # this many characters are needed before results come (0 = always)
CANDIDATE_LIMIT = 50


@router.get("/candidates")
def list_candidates(
    server_id: uuid.UUID, access: AccessManage, db: DbSession, q: str = ""
) -> list[dict[str, str]]:
    """Users who can still be added to this server (for the dropdown)."""
    import sqlalchemy as sa

    from app import models as orm
    from app.models.server import ServerMember as Member

    del access  # only for the permission check
    term = q.strip()[:100]
    if len(term) < CANDIDATE_MIN_QUERY:
        return []
    owner_id = db.execute(
        sa.select(orm.Server.owner_id).where(orm.Server.id == server_id)
    ).scalar_one_or_none()
    members = sa.select(Member.user_id).where(Member.server_id == server_id)
    query = sa.select(orm.User.id, orm.User.email).where(
        orm.User.disabled_at.is_(None),
        orm.User.is_admin.is_(False),
        orm.User.id.not_in(members),
        orm.User.id != owner_id,
    )
    if term:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(orm.User.email.ilike(f"%{escaped}%", escape="\\"))
    rows = db.execute(query.order_by(orm.User.email).limit(CANDIDATE_LIMIT)).all()
    return [{"id": str(row.id), "email": row.email} for row in rows]
