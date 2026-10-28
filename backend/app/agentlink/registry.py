import contextlib
import uuid
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from app.agentlink.protocol import WS_POLICY_VIOLATION, WS_REPLACED


class AgentRegistry:
    """Hält die offenen Agent-Verbindungen. Lebt nur im Speicher dieses Prozesses."""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, WebSocket] = {}
        # Letzte Messwerte pro Node, werden später für die Serverkarten gebraucht.
        self.stats: dict[uuid.UUID, dict[str, Any]] = {}

    async def register(self, node_id: uuid.UUID, websocket: WebSocket) -> None:
        previous = self._connections.get(node_id)
        self._connections[node_id] = websocket
        if previous is not None:
            # Pro Node gibt es nur eine Verbindung, die neuere ersetzt die ältere.
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await previous.close(code=WS_REPLACED)

    def unregister(self, node_id: uuid.UUID, websocket: WebSocket) -> bool:
        """True, wenn es die aktuelle Verbindung war (nicht eine bereits ersetzte)."""
        if self._connections.get(node_id) is not websocket:
            return False
        del self._connections[node_id]
        self.stats.pop(node_id, None)
        return True

    async def disconnect(self, node_id: uuid.UUID) -> None:
        """Schließt die Verbindung einer Node (Widerruf, Löschen)."""
        websocket = self._connections.get(node_id)
        if websocket is not None:
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close(code=WS_POLICY_VIOLATION)

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return node_id in self._connections


registry = AgentRegistry()
