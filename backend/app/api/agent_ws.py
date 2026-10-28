import asyncio
import base64
import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agentlink import protocol
from app.agentlink.registry import registry
from app.db import get_db
from app.models import Node, NodeCredential
from app.security.ratelimit import agent_auth_limiter
from app.services import audit

log = logging.getLogger("epicwing.agent")
router = APIRouter(prefix="/agent", tags=["agent"])


# Die Datenbankzugriffe sind synchron und laufen im Threadpool. Jeder endet mit einem
# Commit, damit die Verbindung zwischen zwei Heartbeats zurück in den Pool geht.
def _load_public_key(db: Session, node_id: uuid.UUID) -> str | None:
    key = db.scalar(
        select(NodeCredential.public_key).where(
            NodeCredential.node_id == node_id, NodeCredential.revoked_at.is_(None)
        )
    )
    db.commit()
    return key


def _mark_online(db: Session, node_id: uuid.UUID, beat: protocol.Heartbeat | None) -> None:
    node = db.get(Node, node_id)
    if node is not None and node.status != "pending":
        node.status = "online"
        node.last_heartbeat_at = datetime.now(UTC)
        if beat is not None:
            node.cpu_total = beat.cpu_total
            node.ram_total_mb = beat.ram_total_mb
            node.disk_total_mb = beat.disk_total_mb
            if beat.agent_version:
                node.agent_version = beat.agent_version
    db.commit()


def _mark_offline(db: Session, node_id: uuid.UUID) -> None:
    node = db.get(Node, node_id)
    if node is not None and node.status == "online":
        node.status = "offline"
    db.commit()


async def _check_auth(
    db: Session, raw: str, nonce: bytes
) -> tuple[uuid.UUID | None, str]:
    """Gibt (node_id, "") bei Erfolg zurück, sonst (None, Grund)."""
    if len(raw) > protocol.MAX_MESSAGE_CHARS:
        return None, "bad_message"
    try:
        hello = protocol.AuthMessage.model_validate_json(raw)
    except ValidationError:
        return None, "bad_message"

    public_key = await run_in_threadpool(_load_public_key, db, hello.node_id)
    if public_key is None:
        return None, "unknown_or_revoked"
    if not protocol.verify_signature(public_key, hello.node_id, nonce, hello.signature):
        return None, "bad_signature"
    return hello.node_id, ""


async def _authenticate(
    websocket: WebSocket, db: Session, nonce: bytes, ip: str
) -> uuid.UUID | None:
    node_id: uuid.UUID | None = None
    reason = "bad_message"
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), protocol.AUTH_TIMEOUT_SECONDS)
    except WebSocketDisconnect:
        return None
    except TimeoutError:
        reason = "timeout"
    except KeyError:
        # Binärer Frame statt Text.
        reason = "bad_message"
    else:
        node_id, reason = await _check_auth(db, raw, nonce)

    if node_id is None:
        agent_auth_limiter.add_failure(ip)
        await run_in_threadpool(
            audit.record, db, "node.agent_auth_failed", ip=ip, details={"reason": reason}
        )
        await websocket.close(code=protocol.WS_POLICY_VIOLATION)
        return None
    return node_id


async def _heartbeat_loop(websocket: WebSocket, db: Session, node_id: uuid.UUID) -> None:
    while True:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), protocol.IDLE_TIMEOUT_SECONDS)
        except WebSocketDisconnect:
            return
        except TimeoutError:
            await websocket.close(code=protocol.WS_GOING_AWAY)
            return
        except KeyError:
            await websocket.close(code=protocol.WS_UNSUPPORTED)
            return

        if len(raw) > protocol.MAX_MESSAGE_CHARS:
            await websocket.close(code=protocol.WS_TOO_BIG)
            return
        try:
            beat = protocol.Heartbeat.model_validate_json(raw)
        except ValidationError:
            await websocket.send_json({"type": "error", "message": "Invalid message."})
            continue

        registry.stats[node_id] = beat.model_dump(exclude={"type"})
        await run_in_threadpool(_mark_online, db, node_id, beat)
        await websocket.send_json({"type": "heartbeat_ack"})


@router.websocket("/ws")
async def agent_socket(websocket: WebSocket, db: Annotated[Session, Depends(get_db)]) -> None:
    # Die Anmeldung läuft über eine Signatur, nicht über Cookies. Ein Origin-Header
    # spielt deshalb keine Rolle: Ein Browser kann diese Signatur nicht erzeugen.
    ip = websocket.client.host if websocket.client else "unknown"
    if agent_auth_limiter.retry_after(ip):
        await websocket.close(code=protocol.WS_POLICY_VIOLATION)
        return
    await websocket.accept()

    nonce = secrets.token_bytes(protocol.NONCE_BYTES)
    await websocket.send_json({"type": "challenge", "nonce": base64.b64encode(nonce).decode()})

    node_id = await _authenticate(websocket, db, nonce, ip)
    if node_id is None:
        return

    await registry.register(node_id, websocket)
    try:
        # Erst online setzen, dann auth_ok senden: Wer auth_ok bekommt, ist auch online.
        await run_in_threadpool(_mark_online, db, node_id, None)
        await websocket.send_json({"type": "auth_ok"})
        log.info("Agent %s verbunden", node_id)
        await _heartbeat_loop(websocket, db, node_id)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        # Nur die aktuelle Verbindung setzt die Node auf offline, nicht eine ersetzte.
        if registry.unregister(node_id, websocket):
            await run_in_threadpool(_mark_offline, db, node_id)
        log.info("Agent %s getrennt", node_id)
