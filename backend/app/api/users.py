"""Globale Benutzerverwaltung (Admin-Bereich "Users").

Schutzregeln:
- Nur Administratoren (is_admin) legen Administratoren an, ändern oder deaktivieren sie und
  setzen Passwörter zurück. Verwalter mit users.manage betreuen nur normale Konten.
- Das eigene Konto kann man hier weder deaktivieren noch löschen noch zum Nicht-Admin machen.
  Dadurch bleibt immer mindestens ein aktiver Administrator übrig.
- Deaktivieren und Passwort zurücksetzen beenden alle Sitzungen des Kontos.
- Wer noch Server besitzt oder Verlauf im Audit-Log hat, wird nicht gelöscht.
- Passwörter und E-Mail-Adressen gehören nicht ins Audit-Log, nur die ID des Betroffenen.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Server, User, UserRole
from app.models.server import ServerMember, ServerMemberPermission
from app.security.passwords import hash_password
from app.security.permissions import Permission, require
from app.security.sessions import AuthContext
from app.services import audit

router = APIRouter(prefix="/users", tags=["users"])

Manage = Annotated[AuthContext, Depends(require(Permission.USERS_MANAGE))]
DbSession = Annotated[Session, Depends(get_db)]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if len(email) > 320 or not EMAIL_RE.fullmatch(email):
        raise ValueError("Enter a valid email address.")
    return email


class UserDetail(BaseModel):
    id: uuid.UUID
    email: str
    is_admin: bool
    disabled_at: datetime | None
    created_at: datetime
    two_factor_enabled: bool
    server_count: int


class UserCreate(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=12, max_length=1024)
    is_admin: bool = False

    _email = field_validator("email")(_normalize_email)


class UserUpdate(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    is_admin: bool | None = None

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_email(value)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=12, max_length=1024)


def _detail(user: User, servers: int) -> UserDetail:
    return UserDetail(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        disabled_at=user.disabled_at,
        created_at=user.created_at,
        two_factor_enabled=user.totp_enabled_at is not None,
        server_count=servers,
    )


def _owned(db: Session, user: User) -> int:
    count = db.scalar(select(func.count()).select_from(Server).where(Server.owner_id == user.id))
    return count or 0


def _load(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return user


def _forbidden(message: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, message)


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _guard_target(auth: AuthContext, target: User) -> None:
    if target.is_admin and not auth.user.is_admin:
        raise _forbidden("Only administrators can manage administrators.")


def _not_self(auth: AuthContext, target: User, message: str) -> None:
    if target.id == auth.user.id:
        raise _conflict(message)


def _end_sessions(db: Session, user: User) -> None:
    for session in list(user.sessions):
        db.delete(session)


def _email_taken(db: Session, email: str, except_id: uuid.UUID | None = None) -> bool:
    query = select(User.id).where(func.lower(User.email) == email)
    if except_id is not None:
        query = query.where(User.id != except_id)
    return db.scalar(query) is not None


def _record(db: Session, request: Request, auth: AuthContext, action: str, **details: Any) -> None:
    audit.record(db, action, actor_id=auth.user.id, ip=audit.client_ip(request), details=details)


@router.get("")
def list_users(
    _auth: Manage,
    db: DbSession,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserDetail]:
    query = select(User).order_by(User.created_at)
    if q and q.strip():
        term = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(func.lower(User.email).like(f"%{term}%", escape="\\"))
    users = db.scalars(query.limit(limit).offset(offset)).all()
    rows = db.execute(
        select(Server.owner_id, func.count())
        .where(Server.owner_id.in_([u.id for u in users]))
        .group_by(Server.owner_id)
    ).all()
    counts = {owner_id: count for owner_id, count in rows}
    return [_detail(u, counts.get(u.id, 0)) for u in users]


@router.get("/{user_id}")
def get_user(user_id: uuid.UUID, _auth: Manage, db: DbSession) -> UserDetail:
    user = _load(db, user_id)
    return _detail(user, _owned(db, user))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, request: Request, auth: Manage, db: DbSession) -> UserDetail:
    if body.is_admin and not auth.user.is_admin:
        raise _forbidden("Only administrators can create administrators.")
    if _email_taken(db, body.email):
        raise _conflict("A user with this email already exists.")
    user = User(
        email=body.email, password_hash=hash_password(body.password), is_admin=body.is_admin
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _conflict("A user with this email already exists.") from None
    _record(db, request, auth, "user.create", user_id=str(user.id), is_admin=user.is_admin)
    db.commit()
    db.refresh(user)
    return _detail(user, 0)


@router.patch("/{user_id}")
def update_user(
    user_id: uuid.UUID, body: UserUpdate, request: Request, auth: Manage, db: DbSession
) -> UserDetail:
    user = _load(db, user_id)
    _guard_target(auth, user)
    changed: list[str] = []
    if body.is_admin is not None and body.is_admin != user.is_admin:
        if not auth.user.is_admin:
            raise _forbidden("Only administrators can change the administrator flag.")
        if not body.is_admin:
            _not_self(auth, user, "You cannot remove your own administrator access.")
        user.is_admin = body.is_admin
        changed.append("is_admin")
    if body.email is not None and body.email != user.email.lower():
        if _email_taken(db, body.email, user.id):
            raise _conflict("A user with this email already exists.")
        user.email = body.email
        changed.append("email")
    if changed:
        _record(db, request, auth, "user.update", user_id=str(user.id), changed=changed)
        db.commit()
        db.refresh(user)
    return _detail(user, _owned(db, user))


@router.post("/{user_id}/disable")
def disable_user(user_id: uuid.UUID, request: Request, auth: Manage, db: DbSession) -> UserDetail:
    user = _load(db, user_id)
    _guard_target(auth, user)
    _not_self(auth, user, "You cannot disable your own account.")
    if user.disabled_at is None:
        user.disabled_at = datetime.now(UTC)
        _end_sessions(db, user)
        _record(db, request, auth, "user.disable", user_id=str(user.id))
        db.commit()
        db.refresh(user)
    return _detail(user, _owned(db, user))


@router.post("/{user_id}/enable")
def enable_user(user_id: uuid.UUID, request: Request, auth: Manage, db: DbSession) -> UserDetail:
    user = _load(db, user_id)
    _guard_target(auth, user)
    if user.disabled_at is not None:
        user.disabled_at = None
        _record(db, request, auth, "user.enable", user_id=str(user.id))
        db.commit()
        db.refresh(user)
    return _detail(user, _owned(db, user))


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: uuid.UUID, body: PasswordReset, request: Request, auth: Manage, db: DbSession
) -> None:
    if not auth.user.is_admin:
        raise _forbidden("Only administrators can reset passwords.")
    user = _load(db, user_id)
    _not_self(auth, user, "Use your account settings to change your own password.")
    user.password_hash = hash_password(body.new_password)
    _end_sessions(db, user)
    _record(db, request, auth, "user.password_reset", user_id=str(user.id))
    db.commit()


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: uuid.UUID, request: Request, auth: Manage, db: DbSession) -> None:
    user = _load(db, user_id)
    _guard_target(auth, user)
    _not_self(auth, user, "You cannot delete your own account.")
    if _owned(db, user):
        raise _conflict("This user still owns servers. Transfer or delete them first.")
    _end_sessions(db, user)
    member_ids = select(ServerMember.id).where(ServerMember.user_id == user.id)
    db.execute(
        delete(ServerMemberPermission).where(ServerMemberPermission.member_id.in_(member_ids))
    )
    db.execute(delete(ServerMember).where(ServerMember.user_id == user.id))
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.delete(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _conflict(
            "This user has recorded activity and cannot be deleted. Disable the account instead."
        ) from None
    _record(db, request, auth, "user.delete", user_id=str(user_id))
    db.commit()
