"""Meldungen bei Node-Ausfall und Rückkehr, mit Karenzzeit gegen kurze Verbindungsabbrüche."""

import asyncio
import logging
import uuid

from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Node
from app.services.notify import notify

log = logging.getLogger("epicwing.node_alerts")

OFFLINE_GRACE_SECONDS = 60

_pending: dict[uuid.UUID, asyncio.Task[None]] = {}
_alerted: set[uuid.UUID] = set()


def _node_info(node_id: uuid.UUID) -> tuple[str, str] | None:
    with Session(get_engine()) as db:
        node = db.get(Node, node_id)
        if node is None:
            return None
        return node.status, str(getattr(node, "name", "") or node_id)


def _deliver(title: str, text: str) -> None:
    with Session(get_engine()) as db:
        notify(db, title, text)


async def _offline_after_delay(node_id: uuid.UUID, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
        info = await asyncio.to_thread(_node_info, node_id)
        if info is None or info[0] != "offline":
            return
        _alerted.add(node_id)
        text = f"Node {info[1]} lost its connection to the panel."
        await asyncio.to_thread(_deliver, "Node offline", text)
    except Exception:
        log.exception("Offline alert for node %s failed", node_id)
    finally:
        if _pending.get(node_id) is asyncio.current_task():
            _pending.pop(node_id, None)


def schedule_offline_alert(node_id: uuid.UUID, delay: float = OFFLINE_GRACE_SECONDS) -> None:
    old = _pending.pop(node_id, None)
    if old is not None:
        old.cancel()
    loop = asyncio.get_running_loop()
    _pending[node_id] = loop.create_task(_offline_after_delay(node_id, delay))


async def on_node_online(node_id: uuid.UUID) -> None:
    """Bricht eine wartende Offline-Meldung ab und meldet die Rückkehr, falls nötig."""
    try:
        task = _pending.pop(node_id, None)
        if task is not None:
            task.cancel()
        if node_id in _alerted:
            _alerted.discard(node_id)
            info = await asyncio.to_thread(_node_info, node_id)
            name = info[1] if info else str(node_id)
            text = f"Node {name} is connected again."
            await asyncio.to_thread(_deliver, "Node back online", text)
    except Exception:
        log.exception("Online alert for node %s failed", node_id)
