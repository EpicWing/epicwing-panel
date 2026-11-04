"""Stores the traffic history of the attack detection, so it survives a restart."""

import asyncio
import logging
import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.ddos import DdosRollup, DdosSample
from app.services.ddos_detect import HISTORY_SECONDS, detector
from app.services.schedule_runner import open_session

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 30
ROLLUP_SECONDS = 300  # 5 minutes per rollup window
ROLLUP_RETENTION = 14 * 24 * 3600  # rollups are kept for 14 days


def flush(db: Session, now_mono: float, now_wall: float, after: int) -> int:
    """Writes new, finished buckets and deletes old ones. Returns the newest bucket."""
    newest = after
    rollups: dict[tuple[str, int], tuple[int, int]] = {}
    for container, bucket, rx, tx in detector.export_buckets(now_mono, now_wall, after):
        db.merge(DdosSample(container=container, bucket=bucket, rx=rx, tx=tx))
        newest = max(newest, bucket)
        window = bucket // ROLLUP_SECONDS * ROLLUP_SECONDS
        old_rx, old_tx = rollups.get((container, window), (0, 0))
        rollups[(container, window)] = (max(old_rx, rx), max(old_tx, tx))
    for (container, window), (rx, tx) in rollups.items():
        row = db.get(DdosRollup, (container, window))
        if row is None:
            db.add(DdosRollup(container=container, bucket=window, rx=rx, tx=tx))
        else:
            row.rx, row.tx = max(row.rx, rx), max(row.tx, tx)
    db.execute(delete(DdosSample).where(DdosSample.bucket < int(now_wall) - HISTORY_SECONDS))
    db.execute(delete(DdosRollup).where(DdosRollup.bucket < int(now_wall) - ROLLUP_RETENTION))
    db.commit()
    return newest


def history_range(
    db: Session, container: str, seconds: int, now_wall: float
) -> tuple[list[int], list[int]]:
    """rx/tx maxima in 5-minute steps of the last `seconds`, oldest first. Gaps are 0."""
    count = max(1, seconds // ROLLUP_SECONDS)
    first = int(now_wall) // ROLLUP_SECONDS * ROLLUP_SECONDS - (count - 1) * ROLLUP_SECONDS
    rx, tx = [0] * count, [0] * count
    rows = db.execute(
        select(DdosRollup.bucket, DdosRollup.rx, DdosRollup.tx).where(
            DdosRollup.container == container, DdosRollup.bucket >= first
        )
    ).all()
    for bucket, rx_value, tx_value in rows:
        i = (bucket - first) // ROLLUP_SECONDS
        if 0 <= i < count:
            rx[i], tx[i] = rx_value, tx_value
    return rx, tx


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
