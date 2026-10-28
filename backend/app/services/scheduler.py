"""Scheduler: startet fällige Zeitpläne. Läuft als Hintergrundaufgabe im Panel-Prozess."""

import asyncio
import contextlib
import logging
import os
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Schedule
from app.services import ddos_store
from app.services.schedule_runner import open_session, run_in_background
from app.services.schedules import build_expression, next_run

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 30
# Ein Termin, der länger überfällig ist (Panel war aus), wird nicht nachgeholt.
GRACE = timedelta(seconds=120)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def tick(db: Session, now: datetime, launch: Callable[[uuid.UUID], None]) -> list[uuid.UUID]:
    """Startet alle fälligen Zeitpläne und setzt ihren nächsten Termin. Gibt die IDs zurück."""
    rows = db.scalars(
        select(Schedule).where(Schedule.enabled.is_(True), Schedule.next_run_at.is_not(None))
    ).all()
    started: list[uuid.UUID] = []
    for row in rows:
        due = _utc(row.next_run_at)
        if due > now:
            continue
        try:
            expression = build_expression(
                row.cron_minute,
                row.cron_hour,
                row.cron_day_of_month,
                row.cron_month,
                row.cron_day_of_week,
            )
        except ValueError:
            row.next_run_at = None
            db.commit()
            log.warning("schedule %s has an invalid cron expression", row.id)
            continue
        # Zuerst den nächsten Termin speichern, dann starten: kein Doppellauf.
        row.next_run_at = next_run(expression, now)
        db.commit()
        if now - due <= GRACE:
            launch(row.id)
            started.append(row.id)
    return started


async def scheduler_loop() -> None:
    while True:
        try:
            with open_session() as db:
                tick(db, datetime.now(UTC), lambda sid: run_in_background(sid, "schedule"))
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    tasks: list[asyncio.Task[None]] = []
    if os.environ.get("EPICWING_SCHEDULER", "1") == "1":
        tasks.append(asyncio.create_task(scheduler_loop()))
        tasks.append(asyncio.create_task(ddos_store.store_loop(ddos_store.load())))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
