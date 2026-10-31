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
from tests.factories import make_allocations, make_egg, make_nest
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
    # so a protocol change breaks this test visibly.
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
    # The auth test for HTTP routes skips WebSocket routes, because they
    # Signatur anmelden. Jede neue WebSocket-Route muss deshalb bewusst hier stehen.
    found = {r.path for r in collect_routes(app) if r.websocket}
    assert found == {"/api/agent/ws", "/api/servers/{server_id}/console"}


def _login(client, user):
    response = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _server_on(client, user, node_id, port, nest_name="Games"):
    headers = _login(client, user)
    nest_id = make_nest(client, headers, nest_name)
    egg_id = make_egg(client, headers, nest_id, startup="run")
    allocations = make_allocations(client, headers, node_id, port, port)
    body = {
        "name": f"Game {port}",
        "owner_id": str(user.id),
        "node_id": node_id,
        "egg_id": egg_id,
        "allocation_id": allocations[0],
    }
    created = client.post("/api/servers", json=body, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _stats_frame(name):
    return {
        "type": "stats",
        "name": name,
        "cpu_percent": 10.0,
        "memory_used_bytes": 100,
        "memory_limit_bytes": 200,
        "disk_used_bytes": 300,
        "network_rx_bytes": 0,
        "network_tx_bytes": 0,
        "started_at": "2026-01-01T00:00:00Z",
    }


@pytest.fixture
def clean_stats():
    registry.server_stats.clear()
    registry._stats_nodes.clear()
    yield
    registry.server_stats.clear()
    registry._stats_nodes.clear()


def _eventually(check, timeout=2.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return check()


def test_stats_of_a_foreign_container_are_ignored(client, user, clean_stats):
    node_id, key = _enroll_node(client, user)
    server_id = _server_on(client, user, node_id, 25001)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        ws.send_json(_stats_frame(str(uuid.uuid4())))
        ws.send_json(_stats_frame(server_id))
        # When the connection closes, unregister clears the stats of this node.
        assert _eventually(lambda: len(registry.server_stats) == 1)
        assert server_id in registry.server_stats


def test_stats_of_a_server_of_another_node_are_ignored(client, user, clean_stats):
    node_a, key_a = _enroll_node(client, user, "node-a")
    node_b, key_b = _enroll_node(client, user, "node-b")
    server_b = _server_on(client, user, node_b, 25002)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_a, key_a)
        ws.send_json(_stats_frame(server_b))
        import time

        time.sleep(0.2)
    assert server_b not in registry.server_stats


def test_disconnecting_one_node_keeps_the_stats_of_others(client, user, clean_stats):
    node_a, key_a = _enroll_node(client, user, "node-a")
    node_b, key_b = _enroll_node(client, user, "node-b")
    server_a = _server_on(client, user, node_a, 25001, "Nest A")
    server_b = _server_on(client, user, node_b, 25002, "Nest B")
    with client.websocket_connect(WS_URL) as ws_b:
        _login_agent(ws_b, node_b, key_b)
        with client.websocket_connect(WS_URL) as ws_a:
            _login_agent(ws_a, node_a, key_a)
            ws_a.send_json(_stats_frame(server_a))
            ws_b.send_json(_stats_frame(server_b))
            assert _eventually(lambda: set(registry.server_stats) == {server_a, server_b})
        # Node A ist getrennt: ihre Stats verschwinden, die von Node B bleiben.
        assert _eventually(lambda: set(registry.server_stats) == {server_b})
        assert server_a not in registry.server_stats


def test_stats_feed_the_ddos_detector(client, user, clean_stats):
    import time

    from app.services.ddos_detect import detector

    node_id, key = _enroll_node(client, user)
    server_id = _server_on(client, user, node_id, 25003)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        frame = _stats_frame(server_id)
        frame["console"] = {"window_lines": 5, "bogus": 7}
        ws.send_json(frame)
        assert _eventually(lambda: detector.snapshot(server_id, time.monotonic()) is not None)
    # Beim Trennen vergisst die Registry auch den Zustand des Detektors.
    assert _eventually(lambda: detector.snapshot(server_id, time.monotonic()) is None)


def test_large_result_frame_keeps_the_connection(client, user):
    # A 512 KiB file block is about 700 KB as Base64.
    node_id, key = _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        frame = {
            "type": "result",
            "id": str(uuid.uuid4()),
            "ok": True,
            "data": {"data": "A" * 700_000},
        }
        ws.send_json(frame)
        ws.send_json(HEARTBEAT)
        assert ws.receive_json() == {"type": "heartbeat_ack"}


def test_frame_over_one_mebibyte_is_closed(client, user):
    node_id, key = _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        ws.send_text("A" * (1024 * 1024 + 1))
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1009
