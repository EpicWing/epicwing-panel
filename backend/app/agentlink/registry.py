import contextlib
import uuid
from collections import deque
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from app.agentlink.protocol import WS_POLICY_VIOLATION, WS_REPLACED, WS_REPLACED_REASON
from app.services.ddos_detect import detector

HISTORY_POINTS = 60  # 10 minutes at 10 s steps


def _percent(used: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(min(100.0, max(0.0, used / total * 100)), 1)


class AgentRegistry:
    """Keeps the open agent connections. Lives only in the memory of this process."""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, WebSocket] = {}
        # Latest measurements per node, needed later for the server cards.
        self.stats: dict[uuid.UUID, dict[str, Any]] = {}
        self.history: dict[uuid.UUID, deque[dict[str, float]]] = {}
        self.server_stats: dict[str, dict[str, Any]] = {}
        # Which node a server in server_stats belongs to, so that disconnecting a
        # node only clears its own live values.
        self._stats_nodes: dict[uuid.UUID, set[str]] = {}

    async def register(self, node_id: uuid.UUID, websocket: WebSocket) -> None:
        previous = self._connections.get(node_id)
        self._connections[node_id] = websocket
        if previous is not None:
            # Only one connection per node: the newer one replaces the older one.
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await previous.close(code=WS_REPLACED, reason=WS_REPLACED_REASON)

    def register_stats(self, node_id: uuid.UUID, name: str) -> None:
        self._stats_nodes.setdefault(node_id, set()).add(name)

    def unregister(self, node_id: uuid.UUID, websocket: WebSocket) -> bool:
        """True if it was the current connection (not one that was already replaced)."""
        if self._connections.get(node_id) is not websocket:
            return False
        del self._connections[node_id]
        self.stats.pop(node_id, None)
        self.history.pop(node_id, None)
        for name in self._stats_nodes.pop(node_id, set()):
            self.server_stats.pop(name, None)
            detector.forget(name)
        return True

    async def disconnect(self, node_id: uuid.UUID) -> None:
        """Closes the connection of a node (revoke, delete)."""
        websocket = self._connections.get(node_id)
        if websocket is not None:
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close(code=WS_POLICY_VIOLATION)

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return node_id in self._connections

    def connection(self, node_id: uuid.UUID) -> WebSocket | None:
        return self._connections.get(node_id)

    def record(self, node_id: uuid.UUID, sample: dict[str, Any]) -> None:
        """Saves the latest measurement and adds it to the history."""
        self.stats[node_id] = sample
        points = self.history.setdefault(node_id, deque(maxlen=HISTORY_POINTS))
        points.append(
            {
                "cpu": round(float(sample["cpu_percent"]), 1),
                "ram": _percent(sample["ram_used_mb"], sample["ram_total_mb"]),
                "disk": _percent(sample["disk_used_mb"], sample["disk_total_mb"]),
            }
        )


registry = AgentRegistry()
