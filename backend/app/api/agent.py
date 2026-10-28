from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.agent import AgentEnrolled, AgentEnrollRequest
from app.security.ratelimit import enroll_limiter
from app.services import audit
from app.services import nodes as node_service

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/enroll", status_code=status.HTTP_201_CREATED)
def enroll(
    body: AgentEnrollRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> AgentEnrolled:
    ip = audit.client_ip(request)

    wait = enroll_limiter.retry_after(ip)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts. Please try again later.",
            headers={"Retry-After": str(wait)},
        )

    try:
        node, fingerprint = node_service.enroll_agent(
            db, body.token, body.public_key, body.agent_version
        )
    except node_service.InvalidPublicKeyError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid public key.") from None
    except node_service.EnrollmentError:
        enroll_limiter.add_failure(ip)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired enrollment token."
        ) from None

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This public key is already registered."
        ) from None

    # Nur der Fingerprint, nie der Token.
    audit.record(
        db,
        "node.enroll",
        target_type="node",
        target_id=str(node.id),
        ip=ip,
        details={"fingerprint": fingerprint},
    )
    return AgentEnrolled(node_id=node.id, node_name=node.name)
