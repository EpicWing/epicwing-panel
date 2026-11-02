import base64
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AuditLog, Node, NodeCredential, NodeEnrollment

PASSWORD = "correct-horse-battery"  # noqa: S105


def _public_key() -> str:
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def _admin_headers(client, user):
    response = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _create_node(client, headers, name="node-1"):
    response = client.post("/api/nodes", json={"name": name}, headers=headers)
    assert response.status_code == 201
    body = response.json()
    return body["node"]["id"], body["enrollment"]["token"]


def _enroll(token, public_key=None):
    # The agent has no session, so it uses its own client without cookies.
    payload = {
        "token": token,
        "public_key": public_key or _public_key(),
        "agent_version": "0.1.0",
    }
    return TestClient(app).post("/api/agent/enroll", json=payload)


def test_enroll_registers_the_node(client, db_session, user):
    headers = _admin_headers(client, user)
    node_id, token = _create_node(client, headers)

    response = _enroll(token)
    assert response.status_code == 201
    assert response.json()["node_id"] == node_id
    assert response.json()["node_name"] == "node-1"

    node = db_session.scalars(select(Node)).one()
    assert node.status == "offline"
    assert node.agent_version == "0.1.0"
    credential = db_session.scalars(select(NodeCredential)).one()
    assert len(credential.fingerprint) == 64
    assert credential.revoked_at is None
    assert db_session.scalars(select(NodeEnrollment)).one().used_at is not None


def test_token_works_only_once(client, user):
    headers = _admin_headers(client, user)
    _, token = _create_node(client, headers)
    assert _enroll(token).status_code == 201
    assert _enroll(token).status_code == 401


def test_expired_token_is_rejected(client, db_session, user):
    headers = _admin_headers(client, user)
    _, token = _create_node(client, headers)
    enrollment = db_session.scalars(select(NodeEnrollment)).one()
    enrollment.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    assert _enroll(token).status_code == 401


def test_unknown_token_is_rejected(client):
    assert _enroll("epicwing_enroll_unknown").status_code == 401


def test_invalid_key_does_not_consume_the_token(client, user):
    headers = _admin_headers(client, user)
    _, token = _create_node(client, headers)
    assert _enroll(token, "not base64!!").status_code == 400
    assert _enroll(token, base64.b64encode(b"short").decode()).status_code == 400
    assert _enroll(token).status_code == 201


def test_repeated_wrong_tokens_are_limited(client):
    for _ in range(10):
        assert _enroll("epicwing_enroll_unknown").status_code == 401
    assert _enroll("epicwing_enroll_unknown").status_code == 429


def test_registered_node_cannot_get_a_new_token(client, user):
    headers = _admin_headers(client, user)
    node_id, token = _create_node(client, headers)
    assert _enroll(token).status_code == 201
    response = client.post(f"/api/nodes/{node_id}/enrollment", headers=headers)
    assert response.status_code == 409


def test_same_key_cannot_register_two_nodes(client, user):
    headers = _admin_headers(client, user)
    _, first = _create_node(client, headers, "node-1")
    _, second = _create_node(client, headers, "node-2")
    key = _public_key()
    assert _enroll(first, key).status_code == 201
    assert _enroll(second, key).status_code == 409


def test_enroll_is_audited_without_token(client, db_session, user):
    headers = _admin_headers(client, user)
    node_id, token = _create_node(client, headers)
    assert _enroll(token).status_code == 201
    entry = db_session.scalars(select(AuditLog).where(AuditLog.action == "node.enroll")).one()
    assert entry.actor_id is None
    assert entry.target_id == node_id
    assert "fingerprint" in entry.details
    assert token not in str(entry.details)
