import uuid

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy import func, select

from app.main import app
from app.models import AuditLog, Node, NodeCredential
from tests.test_agent_ws import (
    HEARTBEAT,
    PASSWORD,
    WS_URL,
    _auth_payload,
    _enroll_node,
    _expect_rejected,
    _login_agent,
)

POLICY_VIOLATION = 1008


def _login(client, user):
    response = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _create(client, headers, name="node-1", **fields):
    response = client.post("/api/nodes", json={"name": name, **fields}, headers=headers)
    assert response.status_code == 201
    return response.json()["node"]["id"]


def _count(db_session, model):
    # Counts directly in the database and skips the cache of the test session.
    db_session.expire_all()
    return db_session.scalar(select(func.count()).select_from(model))


def test_detail_requires_login():
    assert TestClient(app).get(f"/api/nodes/{uuid.uuid4()}").status_code == 401


def test_detail_of_unknown_node_is_404(client, user):
    _login(client, user)
    assert client.get(f"/api/nodes/{uuid.uuid4()}").status_code == 404


def test_detail_of_pending_node(client, user):
    node_id = _create(client, _login(client, user))
    body = client.get(f"/api/nodes/{node_id}").json()
    assert body["status"] == "pending"
    assert body["connected"] is False
    assert body["fingerprint"] is None
    assert body["registered_at"] is None


def test_detail_after_enrollment_shows_fingerprint_only(client, user):
    node_id, _key = _enroll_node(client, user)
    body = client.get(f"/api/nodes/{node_id}").json()
    assert len(body["fingerprint"]) == 64
    assert body["registered_at"] is not None
    assert "public_key" not in body
    assert "private_key" not in body


def test_detail_shows_live_values(client, user):
    node_id, key = _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        ws.send_json(HEARTBEAT)
        assert ws.receive_json() == {"type": "heartbeat_ack"}
        body = client.get(f"/api/nodes/{node_id}").json()
        assert body["status"] == "online"
        assert body["connected"] is True
        assert body["cpu_percent"] == 12.5
        assert body["ram_used_mb"] == 2048
        assert body["disk_used_mb"] == 5000


def test_update_node(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers)
    response = client.patch(
        f"/api/nodes/{node_id}",
        json={
            "name": "Falkenstein 1",
            "location": "Falkenstein",
            "fqdn": "Play.Example.com",
            "port_range_start": 26000,
            "port_range_end": 26500,
        },
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Falkenstein 1"
    assert body["location"] == "Falkenstein"
    assert body["fqdn"] == "play.example.com"
    assert (body["port_range_start"], body["port_range_end"]) == (26000, 26500)

    cleared = client.patch(f"/api/nodes/{node_id}", json={"fqdn": None}, headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["fqdn"] is None
    assert cleared.json()["location"] == "Falkenstein"


def test_update_to_own_name_in_other_case_is_allowed(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers, "node-1")
    response = client.patch(f"/api/nodes/{node_id}", json={"name": "NODE-1"}, headers=headers)
    assert response.status_code == 200


def test_update_rejects_duplicate_name(client, user):
    headers = _login(client, user)
    _create(client, headers, "alpha")
    second = _create(client, headers, "beta")
    response = client.patch(f"/api/nodes/{second}", json={"name": "ALPHA"}, headers=headers)
    assert response.status_code == 409


def test_update_checks_ports_against_stored_values(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers, port_range_start=25000, port_range_end=25999)
    response = client.patch(
        f"/api/nodes/{node_id}", json={"port_range_start": 26000}, headers=headers
    )
    assert response.status_code == 422


def test_update_rejects_null_name_and_unknown_fields(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers)
    url = f"/api/nodes/{node_id}"
    assert client.patch(url, json={"name": None}, headers=headers).status_code == 422
    assert client.patch(url, json={"status": "online"}, headers=headers).status_code == 422


def test_revoke_resets_node_and_closes_connection(client, db_session, user):
    node_id, key = _enroll_node(client, user)
    headers = _login(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        response = client.post(f"/api/nodes/{node_id}/revoke", headers=headers)
        assert response.status_code == 200
        assert response.json()["status"] == "pending"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == POLICY_VIOLATION

    assert _count(db_session, NodeCredential) == 0
    db_session.expire_all()
    assert db_session.scalars(select(Node)).one().status == "pending"

    # With the old key the agent cannot get in anymore, a new token works.
    with client.websocket_connect(WS_URL) as ws:
        challenge = ws.receive_json()
        ws.send_json(_auth_payload(node_id, key, challenge))
        _expect_rejected(ws)
    assert client.post(f"/api/nodes/{node_id}/enrollment", headers=headers).status_code == 201


def test_revoke_of_pending_node_is_409(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers)
    assert client.post(f"/api/nodes/{node_id}/revoke", headers=headers).status_code == 409


def test_delete_node_removes_credentials(client, db_session, user):
    node_id, _key = _enroll_node(client, user)
    headers = _login(client, user)
    assert _count(db_session, NodeCredential) == 1
    assert client.delete(f"/api/nodes/{node_id}", headers=headers).status_code == 204
    assert client.get(f"/api/nodes/{node_id}").status_code == 404
    assert _count(db_session, Node) == 0
    assert _count(db_session, NodeCredential) == 0
    assert "node.delete" in db_session.scalars(select(AuditLog.action)).all()
