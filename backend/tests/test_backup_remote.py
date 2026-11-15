import uuid

import pytest
from sqlalchemy import select

from app.api import backups as backups_api
from app.models.server import ServerBackup
from app.services import s3
from tests import test_server_backups as base
from tests.test_server_backups import _add, _name

server = base.server
broker = base.broker
ready = base.ready

STORAGE = {
    "enabled": True,
    "endpoint": "https://s3.example.com",
    "region": "us-east-1",
    "bucket": "bk",
    "access_key": "AK",
    "secret_key": "SK",
}


@pytest.fixture
def storage(db_session, monkeypatch):
    s3.save_config(db_session, STORAGE)
    calls = []
    monkeypatch.setattr(
        s3, "create_multipart", lambda config, key: calls.append("create") or "up-1"
    )
    monkeypatch.setattr(
        s3, "complete_multipart", lambda config, key, upload, tags: calls.append(("done", tags))
    )
    monkeypatch.setattr(s3, "abort_multipart", lambda config, key, upload: calls.append("abort"))
    monkeypatch.setattr(s3, "delete_object", lambda config, key: calls.append(("delete", key)))
    return calls


def _uploading(db_session, server):
    return _add(
        db_session,
        server,
        status="ok",
        remote_state="uploading",
        remote_key="k",
        remote_upload_id="u",
    )


def _row(db_session, backup_id):
    db_session.expire_all()
    return db_session.get(ServerBackup, uuid.UUID(backup_id))


def _list(client, server):
    response = client.get(server.url + "/backups", headers=server.headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_finished_backup_starts_the_upload(client, db_session, ready, broker, storage):
    backup_id = _add(db_session, ready, status="running")
    broker.data["backup.status"] = {"state": "ok", "size": 1234, "sha256": "a" * 64}
    _list(client, ready)
    row = _row(db_session, backup_id)
    assert (row.remote_state, row.remote_upload_id) == ("uploading", "up-1")
    assert row.remote_key.endswith(f"/{backup_id}.tar.gz")
    action, params = broker.calls[-1]
    assert action == "backup.upload"
    assert params["part_size"] == backups_api.PART_MIN
    assert len(params["urls"]) == 1 and "uploadId=up-1" in params["urls"][0]


def test_without_storage_nothing_is_uploaded(client, db_session, ready, broker):
    backup_id = _add(db_session, ready, status="running")
    broker.data["backup.status"] = {"state": "ok", "size": 10}
    _list(client, ready)
    assert _row(db_session, backup_id).remote_state is None
    assert [c[0] for c in broker.calls] == ["backup.status"]


def test_upload_completes_and_drops_the_local_copy(client, db_session, ready, broker, storage):
    backup_id = _uploading(db_session, ready)
    broker.data["backup.status"] = {"state": "ok", "etags": ['"e1"', '"e2"']}
    items = _list(client, ready)
    assert ("done", ['"e1"', '"e2"']) in storage
    row = _row(db_session, backup_id)
    assert (row.remote_state, row.local, row.remote_upload_id) == ("ok", False, None)
    assert ("backup.delete", {"name": _name(ready), "id": backup_id}) in broker.calls
    assert items[0]["remote_state"] == "ok"


def test_keep_local_keeps_the_copy(client, db_session, ready, broker, storage):
    s3.save_config(db_session, {"keep_local": True})
    backup_id = _uploading(db_session, ready)
    broker.data["backup.status"] = {"state": "ok", "etags": ['"e1"']}
    _list(client, ready)
    row = _row(db_session, backup_id)
    assert (row.remote_state, row.local) == ("ok", True)
    assert "backup.delete" not in [c[0] for c in broker.calls]


def test_failed_upload_is_aborted(client, db_session, ready, broker, storage):
    backup_id = _uploading(db_session, ready)
    broker.data["backup.status"] = {"state": "failed", "error": "part 1 of 1: HTTP 403"}
    _list(client, ready)
    assert "abort" in storage
    row = _row(db_session, backup_id)
    assert (row.remote_state, row.local) == ("failed", True)
    assert row.remote_error == "part 1 of 1: HTTP 403"


def test_download_goes_straight_to_the_bucket(client, db_session, ready, broker, storage):
    backup_id = _add(db_session, ready, status="ok", remote_state="ok", remote_key="k", local=False)
    response = client.get(
        f"{ready.url}/backups/{backup_id}/download", headers=ready.headers, follow_redirects=False
    )
    assert response.status_code == 307
    assert response.headers["location"].startswith("https://s3.example.com/bk/k?")
    assert broker.calls == []


def test_restore_downloads_first(client, db_session, ready, broker, storage):
    backup_id = _add(
        db_session,
        ready,
        status="ok",
        remote_state="ok",
        remote_key="k",
        local=False,
        sha256="b" * 64,
    )
    broker.data["backup.fetch"] = {"state": "ok"}
    response = client.post(f"{ready.url}/backups/{backup_id}/restore", headers=ready.headers)
    assert response.status_code == 202, response.text
    assert [c[0] for c in broker.calls] == ["backup.fetch", "backup.restore"]
    assert broker.calls[0][1]["url"].startswith("https://s3.example.com/bk/k?")
    assert _row(db_session, backup_id).local is True


def test_delete_removes_the_cloud_copy(client, db_session, ready, broker, storage):
    backup_id = _add(db_session, ready, status="ok", remote_state="ok", remote_key="k", local=False)
    response = client.delete(f"{ready.url}/backups/{backup_id}", headers=ready.headers)
    assert response.status_code == 204, response.text
    assert ("delete", "k") in storage
    assert "backup.delete" not in [c[0] for c in broker.calls]
    db_session.expire_all()
    assert list(db_session.scalars(select(ServerBackup))) == []


def test_cloud_only_backups_cannot_be_transferred(client, db_session, ready, broker, storage):
    backup_id = _add(db_session, ready, status="ok", remote_state="ok", remote_key="k", local=False)
    response = client.post(
        f"{ready.url}/backups/{backup_id}/transfer",
        json={"target_server_id": str(uuid.uuid4())},
        headers=ready.headers,
    )
    assert response.status_code == 409


def test_retry_upload(client, db_session, ready, broker, storage):
    backup_id = _add(db_session, ready, status="ok", size_bytes=10, remote_state="failed")
    response = client.post(f"{ready.url}/backups/{backup_id}/upload", headers=ready.headers)
    assert response.status_code == 200, response.text
    assert response.json()["remote_state"] == "uploading"
