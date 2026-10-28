"""Meldungen, die ein Agent von sich aus schickt: Konsolenausgabe und Zustandswechsel."""

import json
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agentlink import protocol
from app.agentlink.console import hub
from app.agentlink.registry import registry
from app.models import Server
from app.services.server_state import apply_state


def _owns_container(db: Session, node_id: uuid.UUID, name: str) -> bool:
    """True, wenn der Containername zu einem Server dieser Node gehört."""
    try:
        server_id = uuid.UUID(name)
    except ValueError:
        return False
    server = db.get(Server, server_id)
    return server is not None and server.node_id == node_id


async def handle_frame(db: Session, node_id: uuid.UUID, raw: str) -> bool:
    """True, wenn raw eine Konsolen- oder Zustandsmeldung war (auch eine ungültige)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    kind = data.get("type")
    if kind == "console":
        try:
            frame = protocol.ConsoleFrame.model_validate(data)
        except ValidationError:
            return True
        await hub.publish(node_id, frame.name, {"type": "output", "data": frame.data})
        return True
    if kind == "state":
        try:
            state = protocol.StateFrame.model_validate(data)
        except ValidationError:
            return True
        status = await run_in_threadpool(apply_state, db, node_id, state)
        if status is not None:
            await hub.publish(node_id, state.name, {"type": "status", "status": status})
        return True
    if kind == "stats":
        try:
            stats = protocol.StatsFrame.model_validate(data)
        except ValidationError:
            return True
        payload = {
            "type": "stats",
            "cpu_percent": stats.cpu_percent,
            "memory_used_bytes": stats.memory_used_bytes,
            "memory_limit_bytes": stats.memory_limit_bytes,
            "disk_used_bytes": stats.disk_used_bytes,
            "network_rx_bytes": stats.network_rx_bytes,
            "network_tx_bytes": stats.network_tx_bytes,
            "started_at": stats.started_at,
        }
        if not _owns_container(db, node_id, stats.name):
            return True
        registry.server_stats[stats.name] = payload
        registry.register_stats(node_id, stats.name)
        await hub.publish(
            node_id,
            stats.name,
            payload,
        )
        return True
    return False
