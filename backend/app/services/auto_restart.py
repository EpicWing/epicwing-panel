"""Automatischer Neustart: Ein Server, der von selbst endet, wird wieder gestartet."""

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agentlink.console import hub
from app.db import get_engine
from app.models import Server
from app.services import audit, lifecycle

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 5
# Ein Ende so kurz nach einem automatischen Start zählt als Fehlversuch.
QUICK_EXIT_SECONDS = 300
# So lange nach einer Stopp-Eingabe in der Konsole gilt das Ende als gewollt.
STOP_INPUT_SECONDS = 60
STOP_WORDS = frozenset({"stop", "shutdown", "exit", "quit"})
# Der Startbefehl fehlt: Ein Neustart ändert daran nichts.
NO_RESTART_EXIT_CODES = frozenset({126, 127})

StartFn = Callable[[Session, Server], Awaitable[None]]


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _is_stop_input(data: str, stop_command: str) -> bool:
    words = data.strip().lstrip("/").lower().split()
    if not words:
        return False
    if words[0] in STOP_WORDS:
        return True
    stop = stop_command.strip().lstrip("/").lower().split()
    return bool(stop) and words[0] == stop[0]


def _stop_requested(server: Server, stop_command: str) -> bool:
    recent = hub.last_input(lifecycle.container_name(server.id))
    if recent is None:
        return False
    when, data = recent
    return time.monotonic() - when <= STOP_INPUT_SECONDS and _is_stop_input(data, stop_command)


def _limit_reached(server: Server) -> bool:
    limit = server.auto_restart_max_failures
    return bool(limit) and (server.restart_failures or 0) >= limit


def _give_up(db: Session, server: Server, reason: str) -> None:
    server.restart_due_at = None
    server.status = "error"
    server.last_error = reason[:1024]
    audit.record(
        db,
        "server.auto_restart.gave_up",
        target_type="server",
        target_id=str(server.id),
        details={
            "name": server.name,
            "failures": server.restart_failures,
            "reason": reason[:300],
        },
    )


def plan(
    db: Session,
    server: Server,
    previous_status: str,
    exit_code: int | None,
    stop_command: str = "",
    now: datetime | None = None,
) -> None:
    """Entscheidet nach dem Ende eines Containers, ob und wann neu gestartet wird."""
    now = now or datetime.now(UTC)
    server.restart_due_at = None
    mode = server.auto_restart
    if mode not in ("crash", "always") or previous_status not in ("running", "starting"):
        return
    if exit_code in NO_RESTART_EXIT_CODES:
        return
    if mode == "crash" and exit_code in (0, None):
        return
    if _stop_requested(server, stop_command):
        return

    last = _utc(server.last_auto_start_at) if server.last_auto_start_at else None
    if last is not None and (now - last).total_seconds() < QUICK_EXIT_SECONDS:
        server.restart_failures = (server.restart_failures or 0) + 1
    else:
        server.restart_failures = 0
    if _limit_reached(server):
        _give_up(
            db,
            server,
            f"The server stopped again within 5 minutes after {server.restart_failures} "
            "automatic restarts. Automatic restart is paused until you start the server.",
        )
        return
    delay = server.auto_restart_delay or 0
    server.restart_due_at = now + timedelta(seconds=delay)
    audit.record(
        db,
        "server.auto_restart",
        target_type="server",
        target_id=str(server.id),
        details={
            "name": server.name,
            "exit_code": exit_code,
            "delay": delay,
            "failures": server.restart_failures,
        },
    )


def _retry(db: Session, server: Server, now: datetime, reason: str, *, count: bool) -> None:
    if count:
        server.restart_failures = (server.restart_failures or 0) + 1
    if count and _limit_reached(server):
        _give_up(
            db, server, f"Automatic restart failed {server.restart_failures} times: {reason}"
        )
    else:
        delay = max(server.auto_restart_delay or 0, INTERVAL_SECONDS)
        server.restart_due_at = now + timedelta(seconds=delay)
    db.commit()


async def _say(server: Server, text: str) -> None:
    name = lifecycle.container_name(server.id)
    with contextlib.suppress(Exception):
        await hub.publish(server.node_id, name, {"type": "output", "data": text})


async def _perform_start(db: Session, server: Server) -> None:
    # Spät importieren: app.api.servers hängt selbst vom Agent-Teil ab.
    from app.api.servers import perform_power

    await perform_power(db, server, "start")


async def run_due(
    db: Session, now: datetime | None = None, start: StartFn | None = None
) -> list[uuid.UUID]:
    """Startet alle Server, deren Neustart fällig ist. Gibt ihre IDs zurück."""
    now = now or datetime.now(UTC)
    start = start or _perform_start
    rows = db.scalars(select(Server).where(Server.restart_due_at.is_not(None))).all()
    started: list[uuid.UUID] = []
    for server in rows:
        if _utc(server.restart_due_at) > now:
            continue
        db.refresh(server)
        if server.auto_restart == "off" or server.status not in ("offline", "error"):
            # Jemand hat den Server inzwischen selbst gestartet oder die Funktion abgeschaltet.
            server.restart_due_at = None
            db.commit()
            continue
        server.restart_due_at = None
        server.last_auto_start_at = now
        db.commit()
        await _say(server, "[EpicWing] The server stopped by itself. Starting it again ...\n")
        try:
            await start(db, server)
        except HTTPException as exc:
            # 409: Die Node ist nicht erreichbar. Das ist kein Fehlversuch des Servers.
            _retry(db, server, now, str(exc.detail), count=exc.status_code != 409)
        except Exception as exc:
            log.exception("automatic start of server %s failed", server.id)
            _retry(db, server, now, str(exc) or type(exc).__name__, count=True)
        else:
            audit.record(
                db,
                "server.auto_restart.start",
                target_type="server",
                target_id=str(server.id),
                details={"name": server.name},
            )
            db.commit()
            started.append(server.id)
    return started


async def loop() -> None:
    while True:
        try:
            with Session(get_engine(), expire_on_commit=False) as db:
                await run_due(db)
        except Exception:
            log.exception("automatic restart tick failed")
        await asyncio.sleep(INTERVAL_SECONDS)
