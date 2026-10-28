import contextlib
import uuid
from collections import deque
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from app.agentlink.protocol import WS_POLICY_VIOLATION, WS_REPLACED, WS_REPLACED_REASON
from app.services.ddos_detect import detector

HISTORY_POINTS = 60  # bei 10 s Abstand 10 Minuten


def _percent(used: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(min(100.0, max(0.0, used / total * 100)), 1)


class AgentRegistry:
    """Hält die offenen Agent-Verbindungen. Lebt nur im Speicher dieses Prozesses."""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, WebSocket] = {}
        # Letzte Messwerte pro Node, werden später für die Serverkarten gebraucht.
        self.stats: dict[uuid.UUID, dict[str, Any]] = {}
        self.history: dict[uuid.UUID, deque[dict[str, float]]] = {}
        self.server_stats: dict[str, dict[str, Any]] = {}
        # Welcher Node ein Server in server_stats gehört, damit das Trennen einer
        # Node nur die eigenen Live-Werte löscht.
        self._stats_nodes: dict[uuid.UUID, set[str]] = {}

    async def register(self, node_id: uuid.UUID, websocket: WebSocket) -> None:
        previous = self._connections.get(node_id)
        self._connections[node_id] = websocket
        if previous is not None:
            # Pro Node gibt es nur eine Verbindung, die neuere ersetzt die ältere.
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await previous.close(code=WS_REPLACED, reason=WS_REPLACED_REASON)

    def register_stats(self, node_id: uuid.UUID, name: str) -> None:
        self._stats_nodes.setdefault(node_id, set()).add(name)

    def unregister(self, node_id: uuid.UUID, websocket: WebSocket) -> bool:
        """True, wenn es die aktuelle Verbindung war (nicht eine bereits ersetzte)."""
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
        """Schließt die Verbindung einer Node (Widerruf, Löschen)."""
        websocket = self._connections.get(node_id)
        if websocket is not None:
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close(code=WS_POLICY_VIOLATION)

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return node_id in self._connections

    def connection(self, node_id: uuid.UUID) -> WebSocket | None:
        return self._connections.get(node_id)

    def record(self, node_id: uuid.UUID, sample: dict[str, Any]) -> None:
        """Speichert den letzten Messwert und hängt ihn an den Verlauf an."""
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
