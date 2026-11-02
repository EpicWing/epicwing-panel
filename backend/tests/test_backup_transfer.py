import importlib
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Server
from app.models.server import ServerBackup
from app.services import lifecycle
from tests import test_server_power as base
from tests.factories import make_allocations

# The fixture "server" creates a server with a node, an egg and an allocation.
server = base.server


@pytest.fixture
def broker(monkeypatch):
    fake = base.FakeBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


def _row(db_session, server_id):
    return db_session.get(Server, uuid.UUID(server_id))


@pytest.fixture
def pair(client, db_session, user, server):
    """Zwei installierte Server auf derselben Node, beide mit Backup-Limit."""
    source = _row(db_session, server.id)
    allocations = make_allocations(client, server.headers, str(source.node_id), 25002, 25002)
    body = {
        "name": "Game 2",
        "owner_id": str(user.id),
        "node_id": str(source.node_id),
        "egg_id": str(source.egg_id),
        "allocation_id": allocations[0],
    }
    created = client.post("/api/servers", json=body, headers=server.headers)
    assert created.status_code == 201, created.text
    target_id = created.json()["id"]
    for server_id in (server.id, target_id):
        row = _row(db_session, server_id)
        row.status = "offline"
        row.backup_limit = 2
    db_session.commit()
    return SimpleNamespace(source=server, target_id=target_id)


def _backup(db_session, server_id, **values):
    fields = {"name": "Source", "status": "ok", "size_bytes": 10, "sha256": "ab" * 32} | values
    row = ServerBackup(server_id=uuid.UUID(server_id), **fields)
    db_session.add(row)
    db_session.commit()
    return row


def _transfer(client, source, backup_id, target_id, **extra):
    return client.post(
        f"{source.url}/backups/{backup_id}/transfer",
        json={"target_server_id": target_id, **extra},
        headers=source.headers,
    )


def _target_rows(db_session, pair):
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(ServerBackup).where(ServerBackup.server_id == uuid.UUID(pair.target_id))
        )
    )


def test_transfer_copies_the_backup_to_the_other_server(client, db_session, pair, broker):
    backup = _backup(db_session, pair.source.id)
    response = _transfer(client, pair.source, backup.id, pair.target_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "running"
    assert body["name"] == "Source (from Game 1)"
    assert body["id"] != str(backup.id)
    action, params = broker.calls[-1]
    assert action == "backup.copy"
    assert params["name"] == lifecycle.container_name(uuid.UUID(pair.target_id))
    assert params["id"] == body["id"]
    assert params["source_name"] == lifecycle.container_name(uuid.UUID(pair.source.id))
    assert params["source_id"] == str(backup.id)
    assert params["sha256"] == "ab" * 32
    rows = _target_rows(db_session, pair)
    assert [str(r.id) for r in rows] == [body["id"]]


def test_transfer_needs_a_finished_backup(client, db_session, pair, broker):
    backup = _backup(db_session, pair.source.id, status="running")
    assert _transfer(client, pair.source, backup.id, pair.target_id).status_code == 409
    assert "backup.copy" not in broker.actions()


def test_transfer_to_the_same_server_is_rejected(client, db_session, pair, broker):
    backup = _backup(db_session, pair.source.id)
    assert _transfer(client, pair.source, backup.id, pair.source.id).status_code == 409
    assert "backup.copy" not in broker.actions()


def test_transfer_to_an_unknown_server_is_404(client, db_session, pair, broker):
    backup = _backup(db_session, pair.source.id)
    assert _transfer(client, pair.source, backup.id, str(uuid.uuid4())).status_code == 404
    assert "backup.copy" not in broker.actions()


def test_transfer_respects_the_limit_of_the_target(client, db_session, pair, broker):
    _row(db_session, pair.target_id).backup_limit = 1
    db_session.commit()
    _backup(db_session, pair.target_id, name="Already there")
    backup = _backup(db_session, pair.source.id)
    assert _transfer(client, pair.source, backup.id, pair.target_id).status_code == 409
    assert "backup.copy" not in broker.actions()


def test_missing_file_on_the_node_removes_the_new_entry(client, db_session, pair, broker):
    broker.errors["backup.copy"] = "backup file not found"
    backup = _backup(db_session, pair.source.id)
    assert _transfer(client, pair.source, backup.id, pair.target_id).status_code == 404
    assert _target_rows(db_session, pair) == []


def _limit_target_permissions(monkeypatch, granted):
    module = importlib.import_module("app.api.backups")

    def limited(db, user, servers, is_admin):
        return {s.id: set(granted) for s in servers}

    monkeypatch.setattr(module, "effective_permissions", limited)


def test_transfer_needs_the_create_right_on_the_target(
    client, db_session, pair, broker, monkeypatch
):
    _limit_target_permissions(monkeypatch, {"backups.view"})
    backup = _backup(db_session, pair.source.id)
    assert _transfer(client, pair.source, backup.id, pair.target_id).status_code == 403
    assert "backup.copy" not in broker.actions()
    assert _target_rows(db_session, pair) == []


def test_transfer_hides_a_target_without_any_right(client, db_session, pair, broker, monkeypatch):
    _limit_target_permissions(monkeypatch, set())
    backup = _backup(db_session, pair.source.id)
    assert _transfer(client, pair.source, backup.id, pair.target_id).status_code == 404
    assert "backup.copy" not in broker.actions()
    assert _target_rows(db_session, pair) == []
