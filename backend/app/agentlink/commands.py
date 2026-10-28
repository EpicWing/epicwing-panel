"""Befehle vom Panel an Node-Agents und die zugehörigen Ergebnisse."""

import asyncio
import json
import uuid
from typing import Any

from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from app.agentlink import protocol
from app.agentlink.registry import AgentRegistry, registry


class AgentOffline(Exception):  # noqa: N818
    """Die Node hat keine offene Verbindung (mehr)."""


class CommandBroker:
    """Schickt Befehle an Agents und wartet auf das Ergebnis mit derselben ID."""

    def __init__(self, agents: AgentRegistry) -> None:
        self._agents = agents
        self._pending: dict[str, tuple[uuid.UUID, asyncio.Future[protocol.CommandResult]]] = {}

    async def send(
        self,
        node_id: uuid.UUID,
        action: str,
        params: dict[str, Any],
        timeout: float = protocol.COMMAND_TIMEOUT_SECONDS,
    ) -> protocol.CommandResult:
        if action not in protocol.COMMAND_ACTIONS:
            raise ValueError(f"unknown action: {action}")
        websocket = self._agents.connection(node_id)
        if websocket is None:
            raise AgentOffline
        command_id = uuid.uuid4().hex
        future: asyncio.Future[protocol.CommandResult] = asyncio.get_running_loop().create_future()
        self._pending[command_id] = (node_id, future)
        try:
            try:
                await websocket.send_json(
                    {"type": "command", "id": command_id, "action": action, "params": params}
                )
            except (RuntimeError, WebSocketDisconnect) as exc:
                raise AgentOffline from exc
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(command_id, None)

    def resolve(self, node_id: uuid.UUID, result: protocol.CommandResult) -> bool:
        """Nimmt ein Ergebnis nur von der Node an, an die der Befehl ging."""
        entry = self._pending.get(result.id)
        if entry is None or entry[0] != node_id:
            return False
        if not entry[1].done():
            entry[1].set_result(result)
        return True

    def fail_pending(self, node_id: uuid.UUID) -> None:
        """Lässt alle offenen Befehle dieser Node sofort scheitern."""
        for owner, future in list(self._pending.values()):
            if owner == node_id and not future.done():
                future.set_exception(AgentOffline())


broker = CommandBroker(registry)


def fail_pending(node_id: uuid.UUID) -> None:
    broker.fail_pending(node_id)


def handle_result(node_id: uuid.UUID, raw: str) -> bool:
    """True, wenn raw ein Ergebnis-Frame war (auch ein ungültiges oder unbekanntes)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return False
    if not isinstance(data, dict) or data.get("type") != "result":
        return False
    try:
        result = protocol.CommandResult.model_validate(data)
    except ValidationError:
        return True
    broker.resolve(node_id, result)
    return True
