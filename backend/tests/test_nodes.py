import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, NodeEnrollment, User
from app.security.passwords import hash_password
from app.security.sessions import hash_token

PASSWORD = "correct-horse-battery"
NODE = {
    "name": "node-1",
    "location": "Germany",
    "fqdn": "node1.example.test",
    "port_range_start": 25000,
    "port_range_end": 25999,
}


@pytest.fixture
def plain_user(db_session):
    account = User(email="user@example.test", password_hash=hash_password(PASSWORD))
    db_session.add(account)
    db_session.commit()
    return account


def _login(client, email):
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _create(client, headers, **overrides):
    return client.post("/api/nodes", json={**NODE, **overrides}, headers=headers)


def test_nodes_require_login(client):
    assert client.get("/api/nodes").status_code == 401


def test_nodes_forbidden_without_permission(client, user, plain_user):
    headers = _login(client, "user@example.test")
    assert client.get("/api/nodes").status_code == 403
    assert _create(client, headers).status_code == 403


def test_create_node_returns_token_once(client, db_session, user):
    headers = _login(client, user.email)
    response = _create(client, headers)
    assert response.status_code == 201
    body = response.json()
    token = body["enrollment"]["token"]
    assert body["node"]["status"] == "pending"
    assert token.startswith("epicwing_enroll_")

    # The database only stores the hash.
    enrollment = db_session.scalars(select(NodeEnrollment)).one()
    assert enrollment.token_hash == hash_token(token)
    assert token not in enrollment.token_hash

    listing = client.get("/api/nodes")
    assert listing.status_code == 200
    assert [n["name"] for n in listing.json()] == ["node-1"]
    assert token not in listing.text


def test_duplicate_name_is_rejected(client, user):
    headers = _login(client, user.email)
    assert _create(client, headers).status_code == 201
    assert _create(client, headers, name="NODE-1").status_code == 409


def test_invalid_ports_are_rejected(client, user):
    headers = _login(client, user.email)
    assert _create(client, headers, port_range_start=26000).status_code == 422
    assert _create(client, headers, port_range_start=80).status_code == 422
    assert _create(client, headers, port_range_end=70000).status_code == 422


def test_invalid_name_and_host_are_rejected(client, user):
    headers = _login(client, user.email)
    assert _create(client, headers, name="bad;name").status_code == 422
    assert _create(client, headers, name="").status_code == 422
    assert _create(client, headers, fqdn="not a host").status_code == 422


def test_new_enrollment_replaces_old_token(client, db_session, user):
    headers = _login(client, user.email)
    created = _create(client, headers).json()
    node_id = created["node"]["id"]

    response = client.post(f"/api/nodes/{node_id}/enrollment", headers=headers)
    assert response.status_code == 201
    new_token = response.json()["token"]
    assert new_token != created["enrollment"]["token"]

    enrollment = db_session.scalars(select(NodeEnrollment)).one()
    assert enrollment.token_hash == hash_token(new_token)


def test_enrollment_for_unknown_node(client, user):
    headers = _login(client, user.email)
    response = client.post(f"/api/nodes/{uuid.uuid4()}/enrollment", headers=headers)
    assert response.status_code == 404


def test_enrollment_needs_csrf_token(client, user):
    headers = _login(client, user.email)
    node_id = _create(client, headers).json()["node"]["id"]
    assert client.post(f"/api/nodes/{node_id}/enrollment").status_code == 403


def test_node_create_is_audited_without_token(client, db_session, user):
    headers = _login(client, user.email)
    token = _create(client, headers).json()["enrollment"]["token"]
    entry = db_session.scalars(select(AuditLog).where(AuditLog.action == "node.create")).one()
    assert entry.details == {"name": "node-1"}
    assert entry.target_type == "node"
    assert token not in str(entry.details)


def test_create_node_with_only_a_name_uses_defaults(client, user):
    headers = _login(client, user.email)
    response = client.post("/api/nodes", json={"name": "minimal"}, headers=headers)
    assert response.status_code == 201
    node = response.json()["node"]
    assert node["port_range_start"] == 1024
    assert node["port_range_end"] == 65535
    assert node["location"] == ""
    assert node["fqdn"] is None
