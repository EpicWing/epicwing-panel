"""Status of the attack detection of a server."""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.security.server_access import ServerAccess, ServerPermission, server_access
from app.services import lifecycle
from app.services.ddos_detect import BUCKET_SECONDS, STALE_SECONDS, detector

router = APIRouter(prefix="/servers", tags=["servers"])

ServerView = Annotated[ServerAccess, Depends(server_access(ServerPermission.VIEW))]


class DdosHistory(BaseModel):
    step_seconds: int
    rx: list[int]
    tx: list[int]


class DdosStatus(BaseModel):
    online: bool
    level: str
    reasons: list[str]
    samples: int
    rates: dict[str, float | None]
    history: DdosHistory


@router.get("/{server_id}/ddos")
def get_ddos(server_id: uuid.UUID, auth: ServerView) -> DdosStatus:
    name, now = lifecycle.container_name(server_id), time.monotonic()
    rx, tx = detector.history(name, now)
    history = DdosHistory(step_seconds=BUCKET_SECONDS, rx=rx, tx=tx)
    snapshot = detector.snapshot(name, now)
    if snapshot is None or snapshot["age"] > STALE_SECONDS:
        return DdosStatus(
            online=False, level="offline", reasons=[], samples=0, rates={}, history=history
        )
    return DdosStatus(
        online=True,
        level=snapshot["level"],
        reasons=snapshot["reasons"],
        samples=snapshot["samples"],
        rates=snapshot["rates"],
        history=history,
    )
