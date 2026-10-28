"""Meldung bei einem erkannten Angriff.

Läuft im Hintergrund, damit der WebSocket-Handler nie auf Discord oder SMTP wartet.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Server
from app.services.notify import notify

log = logging.getLogger("epicwing.ddos_alerts")

COOLDOWN_SECONDS = 15 * 60

_last_alert: dict[str, float] = {}
_tasks: set[asyncio.Task[None]] = set()


def _deliver(name: str, reasons: Sequence[str]) -> None:
    with Session(get_engine()) as db:
        try:
            server = db.get(Server, uuid.UUID(name))
        except ValueError:
            server = None
        label = server.name if server else name
        detail = "; ".join(reasons) or "unusual traffic"
        notify(db, "Possible attack", f"Server {label}: {detail}")


async def _run(name: str, reasons: Sequence[str]) -> None:
    try:
        await asyncio.to_thread(_deliver, name, reasons)
    except Exception:
        log.exception("Attack alert for %s failed", name)


def schedule(name: str, reasons: Sequence[str], now: float | None = None) -> bool:
    """Startet die Meldung, außer für diesen Server lief kürzlich schon eine."""
    now = time.monotonic() if now is None else now
    last = _last_alert.get(name)
    if last is not None and now - last < COOLDOWN_SECONDS:
        return False
    _last_alert[name] = now
    task = asyncio.get_running_loop().create_task(_run(name, reasons))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True
