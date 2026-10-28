"""Konsole eines Servers im Browser: erst ein Ticket holen, dann per WebSocket verbinden."""

import time
import uuid
from collections import deque
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
from app.models import Server
from app.security.permissions import Permission, require
from app.security.sessions import AuthContext
from app.services import audit, lifecycle

router = APIRouter(prefix="/servers", tags=["console"])

ManageServers = Annotated[AuthContext, Depends(require(Permission.PROJECTS_MANAGE))]
DbSession = Annotated[Session, Depends(get_db)]

MAX_INPUTS = 10
INPUT_WINDOW_SECONDS = 5.0
MAX_FRAME_CHARS = 4096


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


@router.post("/{server_id}/console/ticket")
def console_ticket(server_id: uuid.UUID, auth: ManageServers, db: DbSession) -> dict[str, str]:
    if db.get(Server, server_id) is None:
        raise HTTPException(404, "Server not found.")
    return {"ticket": tickets.issue(auth.user.id, server_id)}


async def _input_loop(websocket: WebSocket, node_id: uuid.UUID, name: str) -> None:
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
        await _input_loop(websocket, node_id, name)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await hub.unsubscribe(name, websocket)
