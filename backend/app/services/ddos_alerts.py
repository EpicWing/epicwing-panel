"""Alert when an attack is detected.

Runs in the background, so the WebSocket handler never waits for Discord or SMTP.
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


def _deliver(name: str, reasons: Sequence[str], layers: Sequence[str] = ()) -> None:
    with Session(get_engine()) as db:
        try:
            server = db.get(Server, uuid.UUID(name))
        except ValueError:
            server = None
        label = server.name if server else name
        detail = "; ".join(reasons) or "unusual traffic"
        joined = ", ".join(layers)
        where = f" (layer: {joined})" if layers else ""
        notify(db, "Possible attack", f"Server {label}{where}: {detail}")


async def _run(name: str, reasons: Sequence[str], layers: Sequence[str] = ()) -> None:
    try:
        await asyncio.to_thread(_deliver, name, reasons, layers)
    except Exception:
        log.exception("Attack alert for %s failed", name)


def schedule(
    name: str, reasons: Sequence[str], now: float | None = None, layers: Sequence[str] = ()
) -> bool:
    """Starts the alert, unless one already ran for this server recently."""
    now = time.monotonic() if now is None else now
    last = _last_alert.get(name)
    if last is not None and now - last < COOLDOWN_SECONDS:
        return False
    _last_alert[name] = now
    task = asyncio.get_running_loop().create_task(_run(name, reasons, layers))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True
