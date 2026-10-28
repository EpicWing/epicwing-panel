from collections.abc import Callable
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, RolePermission, User, UserRole
from app.security.sessions import AuthContext, CurrentAuth


class Permission(StrEnum):
    # Globale Rechte. Projektbezogene Rechte kommen mit der projects-Tabelle.
    USERS_MANAGE = "users.manage"
    NODES_MANAGE = "nodes.manage"
    PROJECTS_MANAGE = "projects.manage"
    AUDIT_VIEW = "audit.view"


def user_permissions(db: Session, user: User) -> set[str]:
    rows = db.scalars(
        select(RolePermission.permission)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .join(Role, Role.id == RolePermission.role_id)
        .where(UserRole.user_id == user.id, Role.scope == "global")
    )
    return set(rows)


def has_permission(db: Session, user: User, permission: Permission) -> bool:
    if user.is_admin:
        return True
    return permission.value in user_permissions(db, user)


def require(permission: Permission) -> Callable[..., AuthContext]:
    """Dependency: Benutzer muss angemeldet sein und das Recht besitzen."""

    def dependency(auth: CurrentAuth, db: Annotated[Session, Depends(get_db)]) -> AuthContext:
        if not has_permission(db, auth.user, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied.")
        return auth

    return dependency
