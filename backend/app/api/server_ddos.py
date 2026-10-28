"""Status der Angriffserkennung eines Servers."""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.security.server_access import ServerAccess, ServerPermission, server_access
from app.services import lifecycle
from app.services.ddos_detect import STALE_SECONDS, detector

router = APIRouter(prefix="/servers", tags=["servers"])

ServerView = Annotated[ServerAccess, Depends(server_access(ServerPermission.VIEW))]


class DdosStatus(BaseModel):
    online: bool
    level: str
    reasons: list[str]
    samples: int
    rates: dict[str, float | None]


@router.get("/{server_id}/ddos")
def get_ddos(server_id: uuid.UUID, auth: ServerView) -> DdosStatus:
    snapshot = detector.snapshot(lifecycle.container_name(server_id), time.monotonic())
    if snapshot is None or snapshot["age"] > STALE_SECONDS:
        return DdosStatus(online=False, level="offline", reasons=[], samples=0, rates={})
    return DdosStatus(
        online=True,
        level=snapshot["level"],
        reasons=snapshot["reasons"],
        samples=snapshot["samples"],
        rates=snapshot["rates"],
    )
