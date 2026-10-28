from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.schemas.auth import UserOut
from app.security.permissions import Permission, require
from app.security.sessions import AuthContext

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
def list_users(
    _auth: Annotated[AuthContext, Depends(require(Permission.USERS_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> list[UserOut]:
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return [UserOut.model_validate(u) for u in users]
