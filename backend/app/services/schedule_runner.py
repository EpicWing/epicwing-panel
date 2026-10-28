"""Führt die Aufgaben eines Zeitplans nacheinander aus (Run Now und Scheduler)."""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agentlink.commands import AgentOffline
from app.agentlink.console import ConsoleError, hub, spawn
from app.api.backups import perform_backup
from app.api.servers import perform_power
from app.db import get_engine
from app.models import Schedule, ScheduleTask, Server
from app.services import audit, lifecycle
from app.services.schedules import POWER_ACTIONS

log = logging.getLogger(__name__)

ONLINE = {"running", "starting"}
# Zeitpläne, die in diesem Prozess gerade laufen. Verhindert Doppelläufe.
_running: set[uuid.UUID] = set()


class TaskError(Exception):
    """Eine Aufgabe konnte nicht ausgeführt werden."""


@dataclass
class RunResult:
    state: str  # ok, failed, skipped, busy, missing
    detail: str = ""


def is_running(schedule_id: uuid.UUID) -> bool:
    return schedule_id in _running


def open_session() -> Session:
    return Session(get_engine(), expire_on_commit=False)


async def run_task(db: Session, server: Server, task: ScheduleTask) -> None:
    if task.action == "power":
        if task.payload not in POWER_ACTIONS:
            raise TaskError("Unknown power action.")
        await perform_power(db, server, task.payload)
    elif task.action == "command":
        db.refresh(server)
        if server.status != "running":
            raise TaskError("The server is not running.")
        data = task.payload if task.payload.endswith("\n") else task.payload + "\n"
        try:
            await hub.send_input(server.node_id, lifecycle.container_name(server.id), data)
        except (AgentOffline, TimeoutError, ConsoleError) as exc:
            raise TaskError(str(exc) or type(exc).__name__) from None
    elif task.action == "backup":
        await perform_backup(db, server, None, task.payload, False, None)
    else:
        raise TaskError("Unknown task type.")


async def run_schedule(
    db: Session,
    schedule_id: uuid.UUID,
    *,
    trigger: str = "manual",
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> RunResult:
    """trigger: 'manual' (Run Now) oder 'schedule'. Nur 'schedule' beachtet 'nur wenn online'."""
    if schedule_id in _running:
        return RunResult("busy", "This schedule is already running.")
    _running.add(schedule_id)
    try:
        return await _run(db, schedule_id, trigger, sleep)
    finally:
        _running.discard(schedule_id)


async def _run(
    db: Session,
    schedule_id: uuid.UUID,
    trigger: str,
    sleep: Callable[[float], Awaitable[None]],
) -> RunResult:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        return RunResult("missing", "Schedule not found.")
    server = db.get(Server, schedule.server_id)
    if server is None:
        return RunResult("missing", "Server not found.")
    db.refresh(server)
    if trigger == "schedule" and schedule.only_when_online and server.status not in ONLINE:
        detail = f"The server is {server.status}."
        schedule.last_result = "skipped"
        schedule.last_detail = detail
        db.commit()
        return RunResult("skipped", detail)

    tasks = list(
        db.scalars(
            select(ScheduleTask)
            .where(ScheduleTask.schedule_id == schedule.id)
            .order_by(ScheduleTask.sequence)
        )
    )
    schedule.last_run_at = datetime.now(UTC)
    db.commit()

    failures: list[str] = []
    result = RunResult("ok")
    for task in tasks:
        if task.time_offset:
            await sleep(task.time_offset)
        try:
            await run_task(db, server, task)
        except (HTTPException, TaskError) as exc:
            reason = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            failures.append(f"task {task.sequence} ({task.action}): {reason}")
            if not task.continue_on_failure:
                break
    if failures:
        result = RunResult("failed", "; ".join(failures))
    schedule.last_result = result.state
    schedule.last_detail = result.detail[:300]
    db.commit()

    audit.record(
        db,
        "server.schedule.run",
        target_type="server",
        target_id=str(server.id),
        details={
            "name": server.name,
            "schedule": schedule.name,
            "trigger": trigger,
            "result": result.state,
            "detail": result.detail[:300],
        },
    )
    return result


def run_in_background(schedule_id: uuid.UUID, trigger: str = "manual") -> None:
    """Startet den Lauf als Hintergrundaufgabe mit eigener Datenbank-Sitzung."""

    async def job() -> None:
        try:
            with open_session() as db:
                await run_schedule(db, schedule_id, trigger=trigger)
        except Exception:
            log.exception("schedule %s failed unexpectedly", schedule_id)

    spawn(job())
