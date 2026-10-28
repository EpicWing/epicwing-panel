import io
from typing import Annotated

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.two_factor import (
    CodeBody,
    PasswordBody,
    PasswordCodeBody,
    RecoveryCodesResponse,
    SetupResponse,
    TwoFactorStatus,
)
from app.security import totp
from app.security.passwords import verify_password
from app.security.ratelimit import password_change_limiter, totp_limiter
from app.security.sessions import AuthContext, CurrentAuth, revoke_other_sessions
from app.services import audit

router = APIRouter(prefix="/auth/2fa", tags=["2fa"])


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many(wait: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many attempts. Please try again later.",
        headers={"Retry-After": str(wait)},
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _qr_svg(uri: str) -> str:
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    svg = buffer.getvalue().decode()
    return svg[svg.index("<svg") :]


def _check_password(db: Session, auth: AuthContext, password: str, request: Request) -> None:
    key = str(auth.user.id)
    wait = password_change_limiter.retry_after(key)
    if wait:
        raise _too_many(wait)
    if not verify_password(auth.user.password_hash, password):
        password_change_limiter.add_failure(key)
        audit.record(db, "auth.2fa_password_failed", actor_id=auth.user.id, ip=_ip(request))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The password is incorrect.")
    password_change_limiter.reset(key)


def _check_code(
    db: Session, auth: AuthContext, code: str, request: Request, allow_recovery: bool
) -> None:
    key = str(auth.user.id)
    wait = totp_limiter.retry_after(key)
    if wait:
        raise _too_many(wait)
    ok = totp.verify_code(db, auth.user, code)
    if not ok and allow_recovery:
        ok = totp.consume_recovery_code(db, auth.user, code)
    if not ok:
        totp_limiter.add_failure(key)
        audit.record(db, "auth.2fa_code_failed", actor_id=auth.user.id, ip=_ip(request))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The code is incorrect.")
    totp_limiter.reset(key)


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


@router.get("")
def get_status(auth: CurrentAuth, db: Annotated[Session, Depends(get_db)]) -> TwoFactorStatus:
    enabled = totp.is_enabled(auth.user)
    remaining = totp.remaining_recovery_codes(db, auth.user) if enabled else 0
    return TwoFactorStatus(enabled=enabled, recovery_codes_remaining=remaining)


@router.post("/setup")
def setup(
    body: PasswordBody,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: Annotated[Session, Depends(get_db)],
) -> SetupResponse:
    _check_password(db, auth, body.password, request)
    if totp.is_enabled(auth.user):
        raise _conflict("Two-factor authentication is already enabled.")
    secret = totp.begin_enrollment(db, auth.user)
    uri = totp.provisioning_uri(secret, auth.user.email)
    audit.record(db, "auth.2fa_setup_started", actor_id=auth.user.id, ip=_ip(request))
    _no_store(response)
    return SetupResponse(secret=secret, otpauth_uri=uri, qr_svg=_qr_svg(uri))


@router.post("/enable")
def enable(
    body: CodeBody,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryCodesResponse:
    if totp.is_enabled(auth.user):
        raise _conflict("Two-factor authentication is already enabled.")
    if not auth.user.totp_secret:
        raise _conflict("Start the setup first.")
    _check_code(db, auth, body.code, request, allow_recovery=False)
    codes = totp.activate(db, auth.user)
    revoke_other_sessions(db, auth.session)
    db.commit()
    audit.record(db, "auth.2fa_enabled", actor_id=auth.user.id, ip=_ip(request))
    _no_store(response)
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/disable", status_code=status.HTTP_204_NO_CONTENT)
def disable(
    body: PasswordCodeBody,
    request: Request,
    auth: CurrentAuth,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    if not totp.is_enabled(auth.user):
        raise _conflict("Two-factor authentication is not enabled.")
    _check_password(db, auth, body.password, request)
    _check_code(db, auth, body.code, request, allow_recovery=True)
    totp.disable(db, auth.user)
    revoke_other_sessions(db, auth.session)
    db.commit()
    audit.record(db, "auth.2fa_disabled", actor_id=auth.user.id, ip=_ip(request))


@router.post("/recovery-codes")
def regenerate_recovery_codes(
    body: PasswordCodeBody,
    request: Request,
    response: Response,
    auth: CurrentAuth,
    db: Annotated[Session, Depends(get_db)],
) -> RecoveryCodesResponse:
    if not totp.is_enabled(auth.user):
        raise _conflict("Two-factor authentication is not enabled.")
    _check_password(db, auth, body.password, request)
    _check_code(db, auth, body.code, request, allow_recovery=False)
    codes = totp.generate_recovery_codes(db, auth.user)
    audit.record(db, "auth.2fa_recovery_regenerated", actor_id=auth.user.id, ip=_ip(request))
    _no_store(response)
    return RecoveryCodesResponse(recovery_codes=codes)
