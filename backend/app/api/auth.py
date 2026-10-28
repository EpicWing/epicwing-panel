import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.schemas.auth import AuthResponse, LoginRequest, PasswordChangeRequest, UserOut
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.ratelimit import login_email_limiter, login_ip_limiter, password_change_limiter
from app.security.sessions import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    CurrentAuth,
    create_session,
    revoke_other_sessions,
    revoke_session,
    revoke_token,
)
from app.services import audit

log = logging.getLogger("epicwing.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> AuthResponse:
    ip = _client_ip(request)
    email = body.email.strip().lower()

    wait = max(login_ip_limiter.retry_after(ip), login_email_limiter.retry_after(email))
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many sign-in attempts. Please try again later.",
            headers={"Retry-After": str(wait)},
        )

    user = db.scalar(select(User).where(User.email == email))
    # Es wird immer ein Hash geprüft, auch wenn die E-Mail nicht existiert.
    valid = verify_password(user.password_hash if user else None, body.password)

    if user is None or not valid or user.disabled_at is not None:
        login_ip_limiter.add_failure(ip)
        login_email_limiter.add_failure(email)
        log.warning("Fehlgeschlagener Login von %s", ip)
        # Die eingegebene E-Mail wird bewusst nicht gespeichert.
        reason = "disabled" if user and valid else "invalid_credentials"
        audit.record(
            db,
            "auth.login_failed",
            actor_id=user.id if user else None,
            ip=ip,
            details={"reason": reason},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    login_email_limiter.reset(email)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    # Eine vorhandene alte Session wird beendet, jeder Login bekommt ein neues Token.
    old_token = request.cookies.get(SESSION_COOKIE)
    if old_token:
        revoke_token(db, old_token)

    token, session = create_session(db, user, ip, request.headers.get("user-agent"))
    audit.record(db, "auth.login", actor_id=user.id, ip=ip)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_MAX_AGE.total_seconds()),
        httponly=True,
        secure=get_settings().is_production,
        samesite="lax",
        path="/",
    )
    return AuthResponse(user=UserOut.model_validate(user), csrf_token=session.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    auth: CurrentAuth,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    revoke_session(db, auth.session)
    audit.record(db, "auth.logout", actor_id=auth.user.id, ip=_client_ip(request))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
def me(auth: CurrentAuth) -> AuthResponse:
    return AuthResponse(
        user=UserOut.model_validate(auth.user), csrf_token=auth.session.csrf_token
    )


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    auth: CurrentAuth,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    ip = _client_ip(request)
    key = str(auth.user.id)

    wait = password_change_limiter.retry_after(key)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts. Please try again later.",
            headers={"Retry-After": str(wait)},
        )

    if not verify_password(auth.user.password_hash, body.current_password):
        password_change_limiter.add_failure(key)
        audit.record(db, "auth.password_change_failed", actor_id=auth.user.id, ip=ip)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The current password is incorrect.")

    if body.new_password == body.current_password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The new password must differ from the current one."
        )

    auth.user.password_hash = hash_password(body.new_password)
    revoke_other_sessions(db, auth.session)
    db.commit()
    password_change_limiter.reset(key)
    # Das Passwort selbst gehört nie ins Audit-Log.
    audit.record(db, "auth.password_change", actor_id=auth.user.id, ip=ip)
