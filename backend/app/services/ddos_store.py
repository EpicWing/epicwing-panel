"""Stores the traffic history of the attack detection, so it survives a restart."""

import asyncio
import logging
import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import DdosSample
from app.services.ddos_detect import HISTORY_SECONDS, detector
from app.services.schedule_runner import open_session

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 30


def flush(db: Session, now_mono: float, now_wall: float, after: int) -> int:
    """Writes new, finished buckets and deletes old ones. Returns the newest bucket."""
    newest = after
    for container, bucket, rx, tx in detector.export_buckets(now_mono, now_wall, after):
        db.merge(DdosSample(container=container, bucket=bucket, rx=rx, tx=tx))
        newest = max(newest, bucket)
    db.execute(delete(DdosSample).where(DdosSample.bucket < int(now_wall) - HISTORY_SECONDS))
    db.commit()
    return newest


def load() -> int:
    """Loads the last hour into the detector. Returns the newest bucket (0 = none)."""
    try:
        now_mono, now_wall = time.monotonic(), time.time()
        with open_session() as db:
            rows = db.execute(
                select(DdosSample.container, DdosSample.bucket, DdosSample.rx, DdosSample.tx)
                .where(DdosSample.bucket >= int(now_wall) - HISTORY_SECONDS)
                .order_by(DdosSample.bucket)
            ).all()
        detector.restore([tuple(row) for row in rows], now_mono, now_wall)
        return max((row[1] for row in rows), default=0)
    except Exception:
        log.exception("could not load ddos history")
        return 0


async def store_loop(after: int) -> None:
    while True:
        await asyncio.sleep(INTERVAL_SECONDS)
        try:
            with open_session() as db:
                after = flush(db, time.monotonic(), time.time(), after)
        except Exception:
            log.exception("could not store ddos history")
