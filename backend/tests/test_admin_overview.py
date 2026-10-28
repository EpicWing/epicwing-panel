import uuid
from datetime import UTC, datetime

import pytest

from app.agentlink.registry import registry
from app.models import Node, Server, User
from app.models.server import ServerBackup
from app.security.passwords import hash_password
from tests.factories import make_egg, make_nest

PASSWORD = "correct-horse-battery"
OVERVIEW = "/api/admin/overview"
LOCATIONS = "/api/admin/locations"


@pytest.fixture
def headers(client, user):
    login = {"email": user.email, "password": PASSWORD}
    response = client.post("/api/auth/login", json=login)
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _node(client, headers, name, location="Germany"):
    body = {"name": name, "location": location, "port_range_start": 25000, "port_range_end": 25999}
    response = client.post("/api/nodes", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["node"]["id"])


def _go_online(db_session, node_id):
    node = db_session.get(Node, node_id)
    node.status = "online"
    node.last_heartbeat_at = datetime.now(UTC)
    db_session.commit()


def _egg(client, headers):
    return uuid.UUID(make_egg(client, headers, make_nest(client, headers)))


def _server(db_session, owner, node_id, egg_id, status="offline", memory=1024, disk=5120):
    row = Server(
        name="Test",
        owner_id=owner.id,
        node_id=node_id,
        egg_id=egg_id,
        image="nginx:1.27-alpine",
        memory_mb=memory,
        cpus=1.0,
        disk_mb=disk,
        status=status,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_admin_routes_need_a_login(client):
    assert client.get(OVERVIEW).status_code == 401
    assert client.get(LOCATIONS).status_code == 401


def test_admin_routes_are_admin_only(client, db_session):
    account = User(email="user@example.test", password_hash=hash_password(PASSWORD))
    db_session.add(account)
    db_session.commit()
    login = {"email": account.email, "password": PASSWORD}
    assert client.post("/api/auth/login", json=login).status_code == 200
    assert client.get(OVERVIEW).status_code == 403
    assert client.get(LOCATIONS).status_code == 403


def test_empty_overview(client, user, headers):
    body = client.get(OVERVIEW).json()
    assert body["nodes"] == {"total": 0, "online": 0, "offline": 0, "pending": 0}
    assert body["servers"] == {"total": 0, "by_status": {}}
    assert body["users"] == {"total": 1, "admins": 1, "disabled": 0}
    assert body["backups"] == {"total": 0, "running": 0, "failed": 0, "size_bytes": 0}
    assert body["node_load"] == []
    assert client.get(LOCATIONS).json() == []


def test_overview_counts(client, user, headers, db_session):
    online = _node(client, headers, "node-a")
    _node(client, headers, "node-b")
    _go_online(db_session, online)
    egg = _egg(client, headers)
    first = _server(db_session, user, online, egg, "running", memory=2048, disk=10240)
    _server(db_session, user, online, egg, "offline", memory=1024, disk=5120)
    for status, size in (("ok", 100), ("ok", 50), ("running", 0), ("failed", 0)):
        db_session.add(ServerBackup(server_id=first.id, name="b", status=status, size_bytes=size))
    db_session.commit()

    body = client.get(OVERVIEW).json()
    assert body["nodes"] == {"total": 2, "online": 1, "offline": 0, "pending": 1}
    assert body["servers"] == {"total": 2, "by_status": {"running": 1, "offline": 1}}
    assert body["backups"] == {"total": 4, "running": 1, "failed": 1, "size_bytes": 150}
    load = {row["name"]: row for row in body["node_load"]}
    assert load["node-a"]["servers"] == 2
    assert load["node-a"]["ram_allocated_mb"] == 3072
    assert load["node-a"]["disk_allocated_mb"] == 15360
    assert load["node-a"]["cpu_percent"] is None
    assert load["node-b"]["servers"] == 0
    assert load["node-b"]["status"] == "pending"


def test_live_values_only_for_connected_nodes(client, user, headers, db_session, monkeypatch):
    node_id = _node(client, headers, "node-a")
    _go_online(db_session, node_id)
    live = {"cpu_percent": 12.5, "ram_used_mb": 2048, "disk_used_mb": 4096}
    monkeypatch.setitem(registry.stats, node_id, live)

    monkeypatch.setattr(registry, "is_connected", lambda _id: True)
    row = client.get(OVERVIEW).json()["node_load"][0]
    assert (row["cpu_percent"], row["ram_used_mb"], row["disk_used_mb"]) == (12.5, 2048, 4096)

    monkeypatch.setattr(registry, "is_connected", lambda _id: False)
    row = client.get(OVERVIEW).json()["node_load"][0]
    assert row["cpu_percent"] is None and row["ram_used_mb"] is None


def test_locations_group_the_nodes(client, user, headers, db_session):
    first = _node(client, headers, "n1", "Germany")
    _node(client, headers, "n2", "Germany")
    _node(client, headers, "n3", "Finland")
    _node(client, headers, "n4", "")
    _go_online(db_session, first)
    _server(db_session, user, first, _egg(client, headers))

    assert client.get(LOCATIONS).json() == [
        {"name": "Finland", "nodes": 1, "online": 0, "servers": 0},
        {"name": "Germany", "nodes": 2, "online": 1, "servers": 1},
        {"name": "", "nodes": 1, "online": 0, "servers": 0},
    ]
