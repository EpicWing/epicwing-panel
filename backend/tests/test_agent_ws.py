import base64
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy import select

from app.agentlink.registry import registry
from app.main import app
from app.models import AuditLog, Node, NodeCredential
from app.security.ratelimit import agent_auth_limiter
from tests.helpers import collect_routes

PASSWORD = "correct-horse-battery"  # noqa: S105
WS_URL = "/api/agent/ws"
POLICY_VIOLATION = 1008
REPLACED = 1012

HEARTBEAT = {
    "type": "heartbeat",
    "cpu_total": 4,
    "ram_total_mb": 8192,
    "disk_total_mb": 102400,
    "cpu_percent": 12.5,
    "ram_used_mb": 2048,
    "disk_used_mb": 5000,
    "agent_version": "0.1.0",
}


@pytest.fixture(autouse=True)
def _reset_agent_limiter():
    agent_auth_limiter.clear()
    yield
    agent_auth_limiter.clear()


def _enroll_node(client, user, name="node-1"):
    login = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert login.status_code == 200
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    created = client.post("/api/nodes", json={"name": name}, headers=headers)
    assert created.status_code == 201
    body = created.json()

    private_key = Ed25519PrivateKey.generate()
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    enrolled = TestClient(app).post(
        "/api/agent/enroll",
        json={
            "token": body["enrollment"]["token"],
            "public_key": base64.b64encode(raw).decode(),
        },
    )
    assert enrolled.status_code == 201
    return body["node"]["id"], private_key


def _auth_payload(node_id, private_key, challenge):
    # Das Byte-Muster steht absichtlich hier und nicht im Servercode importiert,
    # damit eine Protokolländerung diesen Test sichtbar bricht.
    nonce = base64.b64decode(challenge["nonce"])
    message = b"epicwing-agent-auth-v1\n" + node_id.encode() + b"\n" + nonce
    signature = base64.b64encode(private_key.sign(message)).decode()
    return {"type": "auth", "node_id": node_id, "signature": signature}


def _login_agent(ws, node_id, private_key):
    challenge = ws.receive_json()
    assert challenge["type"] == "challenge"
    ws.send_json(_auth_payload(node_id, private_key, challenge))
    assert ws.receive_json() == {"type": "auth_ok"}


def _expect_rejected(ws):
    with pytest.raises(WebSocketDisconnect) as exc:
        ws.receive_json()
    assert exc.value.code == POLICY_VIOLATION


def _last_failure_reason(db_session):
    entry = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "node.agent_auth_failed")
    ).one()
    return entry.details["reason"]


def test_agent_authenticates_and_sends_heartbeat(client, db_session, user):
    node_id, key = _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        assert registry.is_connected(uuid.UUID(node_id))

        ws.send_json(HEARTBEAT)
        assert ws.receive_json() == {"type": "heartbeat_ack"}

        node = db_session.scalars(select(Node)).one()
        assert node.status == "online"
        assert node.cpu_total == 4
        assert node.ram_total_mb == 8192
        assert node.disk_total_mb == 102400
        assert node.agent_version == "0.1.0"
        assert node.last_heartbeat_at is not None


def test_enrolled_node_without_connection_is_offline(client, user):
    _enroll_node(client, user)
    assert client.get("/api/nodes").json()[0]["status"] == "offline"


def test_status_is_derived_from_heartbeat_age(client, db_session, user):
    node_id, key = _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        assert client.get("/api/nodes").json()[0]["status"] == "online"

        node = db_session.scalars(select(Node)).one()
        node.last_heartbeat_at = datetime.now(UTC) - timedelta(minutes=2)
        db_session.commit()
        assert client.get("/api/nodes").json()[0]["status"] == "offline"


def test_wrong_signature_is_rejected(client, db_session, user):
    node_id, _key = _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as ws:
        challenge = ws.receive_json()
        ws.send_json(_auth_payload(node_id, Ed25519PrivateKey.generate(), challenge))
        _expect_rejected(ws)
    assert _last_failure_reason(db_session) == "bad_signature"


def test_unknown_node_is_rejected(client, db_session, user):
    _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as ws:
        challenge = ws.receive_json()
        ws.send_json(_auth_payload(str(uuid.uuid4()), Ed25519PrivateKey.generate(), challenge))
        _expect_rejected(ws)
    assert _last_failure_reason(db_session) == "unknown_or_revoked"


def test_revoked_credential_is_rejected(client, db_session, user):
    node_id, key = _enroll_node(client, user)
    credential = db_session.scalars(select(NodeCredential)).one()
    credential.revoked_at = datetime.now(UTC)
    db_session.commit()

    with client.websocket_connect(WS_URL) as ws:
        challenge = ws.receive_json()
        ws.send_json(_auth_payload(node_id, key, challenge))
        _expect_rejected(ws)
    assert _last_failure_reason(db_session) == "unknown_or_revoked"


def test_recorded_signature_cannot_be_replayed(client, db_session, user):
    node_id, key = _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as ws:
        challenge = ws.receive_json()
        recorded = _auth_payload(node_id, key, challenge)
        ws.send_json(recorded)
        assert ws.receive_json() == {"type": "auth_ok"}

    # Neue Verbindung, neue Nonce: Die alte Signatur passt nicht mehr.
    with client.websocket_connect(WS_URL) as ws:
        ws.receive_json()
        ws.send_json(recorded)
        _expect_rejected(ws)
    assert _last_failure_reason(db_session) == "bad_signature"


def test_malformed_first_message_is_rejected(client, db_session):
    with client.websocket_connect(WS_URL) as ws:
        ws.receive_json()
        ws.send_json({"type": "nope"})
        _expect_rejected(ws)
    assert _last_failure_reason(db_session) == "bad_message"


def test_invalid_heartbeat_keeps_the_connection(client, user):
    node_id, key = _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        ws.send_json({"type": "heartbeat", "cpu_total": -1})
        assert ws.receive_json()["type"] == "error"
        ws.send_json(HEARTBEAT)
        assert ws.receive_json() == {"type": "heartbeat_ack"}


def test_repeated_failures_are_limited(client):
    for _ in range(10):
        with client.websocket_connect(WS_URL) as ws:
            ws.receive_json()
            ws.send_json({"type": "nope"})
            _expect_rejected(ws)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(WS_URL):
        pass


def test_newer_connection_replaces_the_older_one(client, db_session, user):
    node_id, key = _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as first:
        _login_agent(first, node_id, key)
        with client.websocket_connect(WS_URL) as second:
            _login_agent(second, node_id, key)
            with pytest.raises(WebSocketDisconnect) as exc:
                first.receive_json()
            assert exc.value.code == REPLACED

            # Die ersetzte Verbindung setzt die Node nicht auf offline.
            assert db_session.scalars(select(Node)).one().status == "online"
            second.send_json(HEARTBEAT)
            assert second.receive_json() == {"type": "heartbeat_ack"}


def test_websocket_routes_are_known():
    # Der Auth-Test für HTTP-Routen überspringt WebSocket-Routen, weil diese sich per
    # Signatur anmelden. Jede neue WebSocket-Route muss deshalb bewusst hier stehen.
    found = {r.path for r in collect_routes(app) if r.websocket}
    assert found == {"/api/agent/ws", "/api/servers/{server_id}/console"}
