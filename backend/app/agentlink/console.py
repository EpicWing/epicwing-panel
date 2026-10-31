"""Konsolen im Panel: Ausgabe der Agents an Browser verteilen, Eingaben als Befehl senden."""

import asyncio
import contextlib
import hashlib
import secrets
import time
import uuid
from collections import deque
from collections.abc import Coroutine
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from app.agentlink.commands import AgentOffline, CommandBroker, broker

TICKET_TTL_SECONDS = 30
COMMAND_TIMEOUT_SECONDS = 15
# This many output blocks the hub keeps per container for browsers that join later.
BACKLOG_FRAMES = 400


class ConsoleError(Exception):
    """Der Agent hat einen Konsolenbefehl abgelehnt."""


class TicketStore:
    """One-time, short-lived tickets for the console WebSocket. Memory only."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[uuid.UUID, uuid.UUID, float]] = {}

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _purge(self) -> None:
        now = time.monotonic()
        for key in [k for k, (_, _, expires) in self._items.items() if expires <= now]:
            del self._items[key]

    def issue(self, user_id: uuid.UUID, server_id: uuid.UUID) -> str:
        self._purge()
        token = secrets.token_urlsafe(32)
        expires = time.monotonic() + TICKET_TTL_SECONDS
        self._items[self._key(token)] = (user_id, server_id, expires)
        return token

    def redeem(self, token: str, server_id: uuid.UUID) -> uuid.UUID | None:
        """Returns the user ID. The ticket is used up after that."""
        self._purge()
        entry = self._items.pop(self._key(token), None)
        if entry is None or entry[1] != server_id:
            return None
        return entry[0]


INSTALL_BACKLOG_FRAMES = 1000


class ConsoleHub:
    """Verteilt die Ausgabe eines Containers an alle Browser, die ihn ansehen."""

    def __init__(self, commands: CommandBroker) -> None:
        self._commands = commands
        self._subs: dict[str, set[WebSocket]] = {}
        self._nodes: dict[str, uuid.UUID] = {}
        self._backlog: dict[str, deque[dict[str, Any]]] = {}
        # Output of install and reinstall, whether or not someone has the console open.
        self._install: dict[str, deque[str]] = {}
        # Last input per container: a typed stop should not be restarted.
        self._last_input: dict[str, tuple[float, str]] = {}

    async def _command(
        self, node_id: uuid.UUID, action: str, name: str, data: str | None = None
    ) -> None:
        params = {"name": name} if data is None else {"name": name, "data": data}
        result = await self._commands.send(node_id, action, params, timeout=COMMAND_TIMEOUT_SECONDS)
        if not result.ok:
            raise ConsoleError(result.error or "The node reported an error.")

    async def subscribe(self, name: str, node_id: uuid.UUID, websocket: WebSocket) -> None:
        subs = self._subs.setdefault(name, set())
        first = not subs
        subs.add(websocket)
        self._nodes[name] = node_id
        if not await self._replay_install(name, websocket):
            return
        if first:
            self._backlog.pop(name, None)
            try:
                await self._command(node_id, "console.watch", name)
            except Exception:
                if name in self._install:
                    # During the installation the output comes through publish_install.
                    return
                self._drop(name, websocket)
                raise
        else:
            # Ein weiterer Browser (z. B. nach einem Neuladen) bekommt die letzten
            # Zeilen nachgeliefert.
            for payload in list(self._backlog.get(name, ())):
                try:
                    await websocket.send_json(payload)
                except (RuntimeError, WebSocketDisconnect):
                    self._drop(name, websocket)
                    return

    def _drop(self, name: str, websocket: WebSocket) -> None:
        subs = self._subs.get(name)
        if subs is None:
            return
        subs.discard(websocket)
        if not subs:
            del self._subs[name]
            self._nodes.pop(name, None)
            self._backlog.pop(name, None)

    async def unsubscribe(self, name: str, websocket: WebSocket) -> None:
        node_id = self._nodes.get(name)
        self._drop(name, websocket)
        if name not in self._subs and node_id is not None:
            from app.services.startup_ready import watcher

            if watcher.watching(name):
                # The panel still waits for the ready message and keeps needing the output.
                return
            with contextlib.suppress(AgentOffline, TimeoutError, ConsoleError):
                await self._command(node_id, "console.unwatch", name)

    async def publish(self, node_id: uuid.UUID, name: str, payload: dict[str, Any]) -> None:
        # Nur die Node, auf der der Container liegt, darf in dessen Konsole schreiben.
        if self._nodes.get(name) != node_id:
            return
        if payload.get("type") == "output":
            self._backlog.setdefault(name, deque(maxlen=BACKLOG_FRAMES)).append(payload)
        for websocket in list(self._subs.get(name, ())):
            try:
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                self._drop(name, websocket)

    def last_input(self, name: str) -> tuple[float, str] | None:
        return self._last_input.get(name)

    async def send_input(self, node_id: uuid.UUID, name: str, data: str) -> None:
        self._last_input[name] = (time.monotonic(), data)
        await self._command(node_id, "console.input", name, data)

    async def _replay_install(self, name: str, websocket: WebSocket) -> bool:
        for data in list(self._install.get(name, ())):
            try:
                await websocket.send_json({"type": "output", "data": data})
            except (RuntimeError, WebSocketDisconnect):
                self._drop(name, websocket)
                return False
        return True

    def start_install(self, name: str) -> None:
        self._install[name] = deque(maxlen=INSTALL_BACKLOG_FRAMES)

    def clear_install(self, name: str) -> None:
        self._install.pop(name, None)

    async def publish_install(self, name: str, data: str) -> None:
        buffer = self._install.setdefault(name, deque(maxlen=INSTALL_BACKLOG_FRAMES))
        buffer.append(data)
        payload = {"type": "output", "data": data}
        for websocket in list(self._subs.get(name, ())):
            try:
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                self._drop(name, websocket)

    async def publish_clear(self, name: str) -> None:
        """Clears the buffers and tells all open consoles to clear their display."""
        self._backlog.pop(name, None)
        self._install.pop(name, None)
        payload = {"type": "clear"}
        for websocket in list(self._subs.get(name, ())):
            try:
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                self._drop(name, websocket)

    async def ensure_watch(self, node_id: uuid.UUID, name: str) -> None:
        """Registers the console with the agent, even without a browser (double watches are harmless)."""
        with contextlib.suppress(AgentOffline, TimeoutError, ConsoleError):
            await self._command(node_id, "console.watch", name)

    async def release(self, node_id: uuid.UUID, name: str) -> None:
        """Beendet den Watch, wenn niemand die Konsole ansieht."""
        if self._subs.get(name):
            return
        with contextlib.suppress(AgentOffline, TimeoutError, ConsoleError):
            await self._command(node_id, "console.unwatch", name)

    async def rewatch(self, node_id: uuid.UUID) -> None:
        """Nach einer neuen Agent-Verbindung die beobachteten Container erneut anmelden."""
        for name, owner in list(self._nodes.items()):
            if owner == node_id and self._subs.get(name):
                with contextlib.suppress(AgentOffline, TimeoutError, ConsoleError):
                    await self._command(node_id, "console.watch", name)


hub = ConsoleHub(broker)
tickets = TicketStore()

_background: set[asyncio.Task[None]] = set()


def spawn(coro: Coroutine[Any, Any, None]) -> None:
    """Starts a background task and keeps a reference until it is done."""
    task = asyncio.get_running_loop().create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
