"""Status of the attack detection of a server."""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.security.server_access import ServerAccess, ServerPermission, server_access
from app.services import lifecycle
from app.services.ddos_detect import BUCKET_SECONDS, STALE_SECONDS, detector
from app.services.ddos_store import ROLLUP_SECONDS, history_range

router = APIRouter(prefix="/servers", tags=["servers"])

ServerView = Annotated[ServerAccess, Depends(server_access(ServerPermission.VIEW))]
DbSession = Annotated[Session, Depends(get_db)]

# Time ranges of the history. Everything above one hour comes from the 5-minute rollups.
RANGES = {"1h": 3600, "24h": 86400, "7d": 7 * 86400, "14d": 14 * 86400}


class DdosHistory(BaseModel):
    step_seconds: int
    rx: list[int]
    tx: list[int]


class DdosStatus(BaseModel):
    online: bool
    level: str
    reasons: list[str]
    layers: list[str]
    samples: int
    rates: dict[str, float | None]
    history: DdosHistory


@router.get("/{server_id}/ddos")
def get_ddos(
    server_id: uuid.UUID,
    auth: ServerView,
    db: DbSession,
    span: Annotated[str, Query(alias="range", pattern="^(1h|24h|7d|14d)$")] = "1h",
) -> DdosStatus:
    name, now = lifecycle.container_name(server_id), time.monotonic()
    if span == "1h":
        rx, tx = detector.history(name, now)
        history = DdosHistory(step_seconds=BUCKET_SECONDS, rx=rx, tx=tx)
    else:
        rx, tx = history_range(db, name, RANGES[span], time.time())
        history = DdosHistory(step_seconds=ROLLUP_SECONDS, rx=rx, tx=tx)
    snapshot = detector.snapshot(name, now)
    if snapshot is None or snapshot["age"] > STALE_SECONDS:
        return DdosStatus(
            online=False,
            level="offline",
            reasons=[],
            layers=[],
            samples=0,
            rates={},
            history=history,
        )
    return DdosStatus(
        online=True,
        level=snapshot["level"],
        reasons=snapshot["reasons"],
        layers=snapshot.get("layers", []),
        samples=snapshot["samples"],
        rates=snapshot["rates"],
        history=history,
    )
