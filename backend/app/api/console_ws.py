"""Konsole eines Servers im Browser: erst ein Ticket holen, dann per WebSocket verbinden."""

import asyncio
import contextlib
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agentlink import protocol
from app.agentlink.commands import AgentOffline
from app.agentlink.console import ConsoleError, hub, tickets
from app.db import get_db
from app.models import Server, User
from app.security.server_access import (
    ServerAccess,
    ServerPermission,
    effective_permissions,
    server_access,
)
from app.services import audit, lifecycle, stats_history

router = APIRouter(prefix="/servers", tags=["console"])

ConsoleViewAccess = Annotated[
    ServerAccess, Depends(server_access(ServerPermission.CONSOLE_VIEW))
]
DbSession = Annotated[Session, Depends(get_db)]

MAX_INPUTS = 10
INPUT_WINDOW_SECONDS = 5.0
MAX_FRAME_CHARS = 4096
# So oft wird bei offener Verbindung geprüft, ob der Benutzer die Konsole noch sehen darf.
ACCESS_RECHECK_SECONDS = 30.0


class InputMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["input"]
    data: str = Field(min_length=1, max_length=1024)

    @field_validator("data")
    @classmethod
    def _no_control_characters(cls, value: str) -> str:
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
            raise ValueError("Control characters are not allowed.")
        return value


def _reason(exc: Exception) -> str:
    if isinstance(exc, AgentOffline):
        return "The node is offline."
    if isinstance(exc, TimeoutError):
        return "The node did not answer in time."
    return str(exc)


def _load(db: Session, server_id: uuid.UUID) -> tuple[uuid.UUID, str, str] | None:
    # populate_existing: Die Session lebt lange, der Status ändert sich in anderen Requests.
    server = db.scalar(
        select(Server).where(Server.id == server_id).execution_options(populate_existing=True)
    )
    found = None if server is None else (server.node_id, server.status, server.name)
    db.commit()
    return found


def _permissions(db: Session, user_id: uuid.UUID, server_id: uuid.UUID) -> set[str]:
    """Aktuelle Rechte des Benutzers. Leer, wenn er den Server nicht mehr nutzen darf."""
    user = db.scalar(
        select(User).where(User.id == user_id).execution_options(populate_existing=True)
    )
    server = db.scalar(
        select(Server).where(Server.id == server_id).execution_options(populate_existing=True)
    )
    allowed: set[str] = set()
    if user is not None and server is not None and user.disabled_at is None:
        allowed = effective_permissions(db, user, [server])[server.id]
    db.commit()
    return allowed


async def _watch_access(
    websocket: WebSocket, has: Callable[[ServerPermission], Awaitable[bool]], interval: float
) -> None:
    """Schließt die Verbindung, sobald der Benutzer die Konsole nicht mehr sehen darf."""
    while True:
        await asyncio.sleep(interval)
        if not await has(ServerPermission.CONSOLE_VIEW):
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=protocol.WS_POLICY_VIOLATION)
            return


@router.post("/{server_id}/console/ticket")
def console_ticket(
    server_id: uuid.UUID, auth: ConsoleViewAccess, db: DbSession
) -> dict[str, str]:
    if db.get(Server, server_id) is None:
        raise HTTPException(404, "Server not found.")
    return {"ticket": tickets.issue(auth.user.id, server_id)}


async def _input_loop(
    websocket: WebSocket,
    node_id: uuid.UUID,
    name: str,
    can_input: Callable[[], Awaitable[bool]],
) -> None:
    recent: deque[float] = deque()
    while True:
        try:
            raw = await websocket.receive_text()
        except KeyError:
            await websocket.close(code=protocol.WS_UNSUPPORTED)
            return
        if len(raw) > MAX_FRAME_CHARS:
            await websocket.close(code=protocol.WS_TOO_BIG)
            return

        now = time.monotonic()
        while recent and now - recent[0] > INPUT_WINDOW_SECONDS:
            recent.popleft()
        if len(recent) >= MAX_INPUTS:
            await websocket.send_json({"type": "error", "message": "Too many inputs."})
            continue
        try:
            message = InputMessage.model_validate_json(raw)
        except ValidationError:
            await websocket.send_json({"type": "error", "message": "Invalid input."})
            continue
        recent.append(now)
        if not await can_input():
            await websocket.send_json({"type": "error", "message": "Permission denied."})
            continue
        try:
            await hub.send_input(node_id, name, message.data)
        except (AgentOffline, TimeoutError, ConsoleError) as exc:
            await websocket.send_json({"type": "error", "message": _reason(exc)})


@router.websocket("/{server_id}/console")
async def console_socket(websocket: WebSocket, server_id: uuid.UUID, db: DbSession) -> None:
    # Die Anmeldung läuft über das Ticket, nicht über Cookies: Eine fremde Webseite
    # kann es nicht beschaffen, weil dafür ein Request mit CSRF-Token nötig ist.
    user_id = tickets.redeem(websocket.query_params.get("ticket", ""), server_id)
    found = await run_in_threadpool(_load, db, server_id) if user_id is not None else None
    if user_id is None or found is None:
        await websocket.close(code=protocol.WS_POLICY_VIOLATION)
        return
    allowed = await run_in_threadpool(_permissions, db, user_id, server_id)
    if ServerPermission.CONSOLE_VIEW.value not in allowed:
        await websocket.close(code=protocol.WS_POLICY_VIOLATION)
        return
    node_id, _status, server_name = found
    await websocket.accept()

    name = lifecycle.container_name(server_id)
    try:
        await hub.subscribe(name, node_id, websocket)
    except (AgentOffline, TimeoutError, ConsoleError) as exc:
        await websocket.send_json({"type": "error", "message": _reason(exc)})
        await websocket.close(code=protocol.WS_GOING_AWAY)
        return

    ip = websocket.client.host if websocket.client else "unknown"
    try:
        await run_in_threadpool(
            audit.record,
            db,
            "server.console_open",
            actor_id=user_id,
            target_type="server",
            target_id=str(server_id),
            ip=ip,
            details={"name": server_name},
        )
        current = await run_in_threadpool(_load, db, server_id)
        await websocket.send_json({"type": "status", "status": current[1] if current else ""})
        samples = stats_history.snapshot(name)
        if samples:
            await websocket.send_json({"type": "history", "samples": samples})
        lock = asyncio.Lock()

        async def has(permission: ServerPermission) -> bool:
            # Die Session wird nie von zwei Threads gleichzeitig benutzt.
            async with lock:
                granted = await run_in_threadpool(_permissions, db, user_id, server_id)
            return permission.value in granted

        async def can_input() -> bool:
            return await has(ServerPermission.CONSOLE_COMMAND)

        watcher = asyncio.create_task(_watch_access(websocket, has, ACCESS_RECHECK_SECONDS))
        try:
            await _input_loop(websocket, node_id, name, can_input)
        finally:
            watcher.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await hub.unsubscribe(name, websocket)
