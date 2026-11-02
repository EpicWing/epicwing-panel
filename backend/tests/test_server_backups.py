import importlib
import re
import sys
import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, Server
from app.models.server import ServerBackup
from tests import test_server_power as base
from tests.test_server_files import BlobBroker, FileBroker

# The fixture "server" creates a server with a node, an egg and an allocation.
server = base.server


@pytest.fixture
def broker(monkeypatch):
    fake = FileBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


def _set(db_session, server, **values):
    row = db_session.get(Server, uuid.UUID(server.id))
    for key, value in values.items():
        setattr(row, key, value)
    db_session.commit()


@pytest.fixture
def ready(db_session, server):
    _set(db_session, server, status="offline", backup_limit=2)
    return server


def _name(server):
    return str(uuid.UUID(server.id))


def _create(client, server, **body):
    return client.post(server.url + "/backups", json=body, headers=server.headers)


def _add(db_session, server, **values):
    row = ServerBackup(server_id=uuid.UUID(server.id), name=values.pop("name", "b"), **values)
    db_session.add(row)
    db_session.commit()
    return str(row.id)


def _rows(db_session):
    db_session.expire_all()
    return list(db_session.scalars(select(ServerBackup)))


def test_backups_are_off_by_default(client, db_session, server, broker):
    _set(db_session, server, status="offline")
    assert _create(client, server).status_code == 409
    assert broker.calls == []
    assert _rows(db_session) == []


@pytest.mark.parametrize("state", ["new", "installing"])
def test_backups_are_blocked_before_the_install_is_done(client, db_session, server, broker, state):
    _set(db_session, server, status=state, backup_limit=2)
    assert _create(client, server).status_code == 409
    assert broker.calls == []


def test_create_starts_the_job(client, db_session, ready, broker):
    response = _create(client, ready, name="Nightly", ignored="logs/\n")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Nightly" and body["status"] == "running"
    assert broker.calls == [
        ("backup.create", {"name": _name(ready), "id": body["id"], "ignored": "logs/\n"})
    ]
    db_session.expire_all()
    assert "server.backup.create" in db_session.scalars(select(AuditLog.action)).all()


def test_create_refuses_over_the_limit(client, db_session, ready, broker):
    _set(db_session, ready, backup_limit=1)
    _add(db_session, ready, status="ok")
    assert _create(client, ready).status_code == 409
    assert broker.calls == []


def test_failed_backups_do_not_count_against_the_limit(client, db_session, ready, broker):
    _set(db_session, ready, backup_limit=1)
    _add(db_session, ready, status="failed")
    assert _create(client, ready).status_code == 201


def test_create_with_offline_node_leaves_no_row(client, db_session, ready, broker):
    broker.offline = True
    assert _create(client, ready).status_code == 409
    assert _rows(db_session) == []


def test_create_maps_agent_busy_to_409(client, db_session, ready, broker):
    broker.errors["backup.create"] = "another backup operation is already running for this server"
    assert _create(client, ready).status_code == 409
    assert _rows(db_session) == []


def test_poll_marks_a_finished_backup(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="running")
    broker.data["backup.status"] = {"state": "ok", "size": 1234, "sha256": "a" * 64}
    response = client.get(ready.url + f"/backups/{backup_id}", headers=ready.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok" and body["size_bytes"] == 1234
    assert body["sha256"] == "a" * 64 and body["completed_at"] is not None
    assert broker.calls == [
        ("backup.status", {"name": _name(ready), "id": backup_id, "kind": "create"})
    ]


def test_poll_marks_a_failed_backup(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="running")
    broker.data["backup.status"] = {"state": "failed", "error": "disk full"}
    body = client.get(ready.url + f"/backups/{backup_id}", headers=ready.headers).json()
    assert body["status"] == "failed" and body["error"] == "disk full"


def test_poll_marks_a_backup_missing_on_the_node(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="running")
    broker.errors["backup.status"] = "backup not found"
    body = client.get(ready.url + f"/backups/{backup_id}", headers=ready.headers).json()
    assert body["status"] == "failed"


def test_poll_keeps_the_state_while_the_node_is_offline(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="running")
    broker.offline = True
    response = client.get(ready.url + f"/backups/{backup_id}", headers=ready.headers)
    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_list_returns_the_limit_and_the_items(client, db_session, ready, broker):
    _add(db_session, ready, status="ok", name="one")
    response = client.get(ready.url + "/backups", headers=ready.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["limit"] == 2 and [i["name"] for i in body["items"]] == ["one"]


def test_backup_of_another_server_is_not_found(client, db_session, ready, broker):
    response = client.get(ready.url + f"/backups/{uuid.uuid4()}", headers=ready.headers)
    assert response.status_code == 404


def test_restore_needs_a_stopped_server(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="ok")
    _set(db_session, ready, status="running")
    response = client.post(ready.url + f"/backups/{backup_id}/restore", headers=ready.headers)
    assert response.status_code == 409
    assert broker.calls == []


def test_restore_refuses_an_unfinished_backup(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="failed")
    response = client.post(ready.url + f"/backups/{backup_id}/restore", headers=ready.headers)
    assert response.status_code == 409
    assert broker.calls == []


def test_restore_starts_the_job(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="ok", sha256="b" * 64)
    response = client.post(ready.url + f"/backups/{backup_id}/restore", headers=ready.headers)
    assert response.status_code == 202, response.text
    assert response.json() == {"state": "running"}
    assert broker.calls == [
        ("backup.restore", {"name": _name(ready), "id": backup_id, "sha256": "b" * 64})
    ]


def test_restore_status_is_passed_through(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="ok")
    broker.data["backup.status"] = {"state": "failed", "error": "boom"}
    response = client.get(ready.url + f"/backups/{backup_id}/restore", headers=ready.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"state": "failed", "error": "boom"}
    assert broker.calls == [
        ("backup.status", {"name": _name(ready), "id": backup_id, "kind": "restore"})
    ]


def test_lock_can_be_toggled(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="ok")
    url = ready.url + f"/backups/{backup_id}"
    response = client.patch(url, json={"is_locked": True}, headers=ready.headers)
    assert response.status_code == 200 and response.json()["is_locked"] is True
    response = client.patch(url, json={"is_locked": False}, headers=ready.headers)
    assert response.json()["is_locked"] is False


def test_delete_refuses_a_locked_backup(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="ok", is_locked=True)
    response = client.delete(ready.url + f"/backups/{backup_id}", headers=ready.headers)
    assert response.status_code == 409
    assert broker.calls == []


def test_delete_refuses_a_running_backup(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="running")
    response = client.delete(ready.url + f"/backups/{backup_id}", headers=ready.headers)
    assert response.status_code == 409
    assert len(_rows(db_session)) == 1


def test_delete_removes_the_file_and_the_row(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="ok")
    response = client.delete(ready.url + f"/backups/{backup_id}", headers=ready.headers)
    assert response.status_code == 204, response.text
    assert broker.calls == [("backup.delete", {"name": _name(ready), "id": backup_id})]
    assert _rows(db_session) == []


# --- Download -----------------------------------------------------------------

DOWNLOAD_NAME = re.compile(r'attachment; filename="(backup-[0-9a-f]{8}\.tar\.gz)"')


class EmptyChunkBroker(BlobBroker):
    """Reports a size but sends no data: the probe block is then incomplete."""

    async def send(self, node_id, action, params, timeout=90):
        result = await super().send(node_id, action, params, timeout)
        result.data["data"] = ""
        return result


def _serve(monkeypatch, content, cls=BlobBroker):
    """Replaces the broker everywhere the download uses it.

    The fixture "ready" has already set a FileBroker in some modules,
    and there is the module where _send lives.
    """
    from app.agentlink.commands import broker as real

    fake = cls(content)
    backups = importlib.import_module("app.api.backups")
    holders = {backups, sys.modules[backups._send.__module__]}
    for name, module in list(sys.modules.items()):
        if not name.startswith("app."):
            continue
        current = getattr(module, "broker", None)
        if current is real or isinstance(current, FileBroker):
            holders.add(module)
    for module in holders:
        if hasattr(module, "broker"):
            monkeypatch.setattr(module, "broker", fake)
    assert backups.broker is fake
    return fake


def _download(client, server, backup_id):
    return client.get(f"{server.url}/backups/{backup_id}/download", headers=server.headers)


def _download_audits(db_session):
    db_session.expire_all()
    rows = db_session.scalars(select(AuditLog))
    return [row for row in rows if "backup" in row.action and "download" in row.action]


def test_download_streams_the_whole_archive(client, db_session, ready, monkeypatch):
    content = bytes(range(256)) * 200 + b"tail"
    fake = _serve(monkeypatch, content)
    backup_id = _add(db_session, ready, status="ok")
    response = _download(client, ready, backup_id)
    assert response.status_code == 200, response.text
    assert response.content == content
    assert response.headers["content-length"] == str(len(content))
    assert response.headers["content-type"] == "application/gzip"
    assert response.headers["cache-control"] == "no-store"
    assert DOWNLOAD_NAME.fullmatch(response.headers["content-disposition"])
    assert sorted(params["offset"] for _, params in fake.calls) == list(
        range(0, len(content), 8 * 1024)
    )
    assert {action for action, _ in fake.calls} == {"backup.read"}
    assert {params["id"] for _, params in fake.calls} == {backup_id}


def test_download_of_an_empty_archive(client, db_session, ready, monkeypatch):
    _serve(monkeypatch, b"")
    response = _download(client, ready, _add(db_session, ready, status="ok"))
    assert response.status_code == 200, response.text
    assert response.content == b""
    assert response.headers["content-length"] == "0"


def test_download_name_is_random_and_hides_the_backup_name(client, db_session, ready, monkeypatch):
    _serve(monkeypatch, b"x")
    backup_id = _add(db_session, ready, status="ok", name="Secret Name")
    responses = [_download(client, ready, backup_id) for _ in range(2)]
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    names = {DOWNLOAD_NAME.fullmatch(r.headers["content-disposition"])[1] for r in responses}
    assert len(names) == 2
    assert all("Secret" not in name for name in names)


def test_download_is_audited_once(client, db_session, ready, monkeypatch):
    _serve(monkeypatch, bytes(20000))
    response = _download(client, ready, _add(db_session, ready, status="ok"))
    assert response.status_code == 200, response.text
    assert len(_download_audits(db_session)) == 1


def test_unfinished_backup_cannot_be_downloaded(client, db_session, ready, monkeypatch):
    fake = _serve(monkeypatch, b"data")
    response = _download(client, ready, _add(db_session, ready))
    assert response.status_code == 409, response.text
    assert fake.calls == []
    assert _download_audits(db_session) == []


def test_unknown_backup_gives_404(client, db_session, ready, monkeypatch):
    fake = _serve(monkeypatch, b"data")
    response = _download(client, ready, uuid.uuid4())
    assert response.status_code == 404, response.text
    assert fake.calls == []
    assert _download_audits(db_session) == []


def test_incomplete_first_chunk_gives_502(client, db_session, ready, monkeypatch):
    _serve(monkeypatch, b"x" * 100, EmptyChunkBroker)
    response = _download(client, ready, _add(db_session, ready, status="ok"))
    assert response.status_code == 502, response.text
    assert _download_audits(db_session) == []
