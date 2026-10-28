"""Meldungen, die ein Agent von sich aus schickt: Konsolenausgabe und Zustandswechsel."""

import json
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agentlink import protocol
from app.agentlink.console import hub
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
    return False
