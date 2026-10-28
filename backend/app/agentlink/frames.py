"""Meldungen, die ein Agent von sich aus schickt: Konsolenausgabe und Zustandswechsel."""

import json
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agentlink import protocol
from app.agentlink.console import hub
from app.agentlink.registry import registry
from app.services.server_state import apply_state


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
        }
        registry.server_stats[stats.name] = payload
        await hub.publish(
            node_id,
            stats.name,
            payload,
        )
        return True
    return False
