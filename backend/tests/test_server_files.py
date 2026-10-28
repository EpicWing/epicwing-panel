import base64
import importlib
import uuid

import pytest
from sqlalchemy import select

from app.agentlink.commands import AgentOffline
from app.agentlink.protocol import CommandResult
from app.models import AuditLog, Node, Server
from tests import test_server_power as base

# Der Fixture "server" legt einen Server mit Node, Egg und Allocation an.
server = base.server


class FileBroker:
    def __init__(self):
        self.calls = []
        self.data = {}
        self.errors = {}
        self.offline = False

    async def send(self, node_id, action, params, timeout=90):
        self.calls.append((action, params))
        if self.offline:
            raise AgentOffline
        error = self.errors.get(action)
        data = None if error else self.data.get(action, {})
        return CommandResult(type="result", id="x", ok=error is None, error=error, data=data)


@pytest.fixture
def broker(monkeypatch):
    fake = FileBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


def _set_status(db_session, server, value):
    db_session.get(Server, uuid.UUID(server.id)).status = value
    db_session.commit()


@pytest.fixture
def ready(db_session, server):
    _set_status(db_session, server, "offline")
    return server


def _name(server):
    return str(uuid.UUID(server.id))


@pytest.mark.parametrize("state", ["new", "installing"])
def test_files_are_blocked_before_the_install_is_done(client, db_session, server, broker, state):
    _set_status(db_session, server, state)
    response = client.get(server.url + "/files", headers=server.headers)
    assert response.status_code == 409
    assert broker.calls == []


def test_list_passes_the_path_through(client, ready, broker):
    listing = {"entries": [{"name": "a", "dir": True}], "total": 1, "next": -1}
    broker.data["file.list"] = listing
    response = client.get(
        ready.url + "/files", params={"path": "logs", "offset": 5}, headers=ready.headers
    )
    assert response.status_code == 200, response.text
    assert response.json() == listing
    assert broker.calls == [("file.list", {"name": _name(ready), "path": "logs", "offset": 5})]


def test_read_passes_the_range_through(client, ready, broker):
    broker.data["file.read"] = {"data": "aGk=", "size": 2, "eof": True}
    response = client.get(
        ready.url + "/files/content",
        params={"path": "a.txt", "offset": 4, "length": 100},
        headers=ready.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"data": "aGk=", "size": 2, "eof": True}
    expected = {"name": _name(ready), "path": "a.txt", "offset": 4, "length": 100}
    assert broker.calls == [("file.read", expected)]


def test_write_passes_the_chunk_through(client, ready, broker):
    body = {"path": "a/b.txt", "offset": 8192, "data": "aGk=", "create": False, "truncate": False}
    response = client.put(ready.url + "/files/content", json=body, headers=ready.headers)
    assert response.status_code == 204, response.text
    assert broker.calls == [("file.write", {"name": _name(ready), **body})]


def test_write_defaults_create_a_file(client, ready, broker):
    body = {"path": "new.txt", "data": ""}
    response = client.put(ready.url + "/files/content", json=body, headers=ready.headers)
    assert response.status_code == 204, response.text
    params = broker.calls[0][1]
    assert params["offset"] == 0 and params["create"] is True and params["truncate"] is False


def test_folder_rename_and_delete(client, ready, broker):
    name = _name(ready)
    steps = [
        ("/files/folder", {"path": "maps"}, "file.mkdir", {"path": "maps"}),
        ("/files/rename", {"path": "a", "to": "b"}, "file.rename", {"path": "a", "to": "b"}),
        (
            "/files/delete",
            {"path": "old", "recursive": True},
            "file.delete",
            {"path": "old", "recursive": True},
        ),
    ]
    for url, body, action, params in steps:
        response = client.post(ready.url + url, json=body, headers=ready.headers)
        assert response.status_code == 204, response.text
        assert broker.calls[-1] == (action, {"name": name, **params})
    assert len(broker.calls) == 3


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ("openat logs/x: no such file or directory", 404),
        ("mkdir maps: file exists", 409),
        ("target already exists", 409),
        ("remove old: directory not empty", 409),
        ("not a regular file", 409),
        ("invalid path", 400),
        ("cannot delete the server root", 400),
        ("openat ../etc/passwd: path escapes from parent", 400),
    ],
)
def test_agent_errors_become_clean_status_codes(client, ready, broker, error, code):
    broker.errors["file.read"] = error
    response = client.get(ready.url + "/files/content", params={"path": "x"}, headers=ready.headers)
    assert response.status_code == code, response.text


def test_unknown_agent_errors_are_not_leaked(client, ready, broker):
    broker.errors["file.list"] = "boom: secret internal detail at /var/lib/epicwing"
    response = client.get(ready.url + "/files", headers=ready.headers)
    assert response.status_code == 502
    assert "secret" not in response.text and "/var/lib" not in response.text


def test_offline_node_gives_409(client, ready, broker):
    broker.offline = True
    response = client.get(ready.url + "/files", headers=ready.headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "The node is offline."


def test_unknown_server_gives_404(client, server, broker):
    url = f"/api/servers/{uuid.uuid4()}/files"
    assert client.get(url, headers=server.headers).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"path": "a", "data": "", "extra": 1},
        {"path": "a", "data": "", "offset": -1},
        {"path": "a", "data": "", "offset": (1 << 30) + 1},
        {"path": "a", "data": "A" * 700_001},
        {"path": "a\x00b", "data": ""},
        {"path": "a" * 1025, "data": ""},
        {"data": ""},
    ],
)
def test_invalid_writes_are_rejected_before_the_agent(client, ready, broker, body):
    response = client.put(ready.url + "/files/content", json=body, headers=ready.headers)
    assert response.status_code == 422
    assert broker.calls == []


@pytest.mark.parametrize("length", [0, 8193])
def test_invalid_read_length_is_rejected(client, ready, broker, length):
    response = client.get(
        ready.url + "/files/content",
        params={"path": "a", "length": length},
        headers=ready.headers,
    )
    assert response.status_code == 422
    assert broker.calls == []


def _audit(db_session, action):
    db_session.expire_all()
    return list(db_session.scalars(select(AuditLog).where(AuditLog.action == action)))


def test_write_is_audited_only_for_the_first_chunk(client, db_session, ready, broker):
    url = ready.url + "/files/content"
    first = {"path": "a.txt", "offset": 0, "data": "aGk="}
    later = {"path": "a.txt", "offset": 8192, "data": "aGk="}
    assert client.put(url, json=first, headers=ready.headers).status_code == 204
    assert client.put(url, json=later, headers=ready.headers).status_code == 204
    entries = _audit(db_session, "server.file.write")
    assert len(entries) == 1
    assert entries[0].details["path"] == "a.txt"
    assert "aGk=" not in str(entries[0].details)


def test_mkdir_rename_and_delete_are_audited(client, db_session, ready, broker):
    steps = [
        ("/files/folder", {"path": "maps"}, "server.file.mkdir"),
        ("/files/rename", {"path": "a", "to": "b"}, "server.file.rename"),
        ("/files/delete", {"path": "old", "recursive": True}, "server.file.delete"),
    ]
    for url, body, action in steps:
        assert client.post(ready.url + url, json=body, headers=ready.headers).status_code == 204
        entries = _audit(db_session, action)
        assert len(entries) == 1
        assert entries[0].details["path"] == body["path"]
    assert _audit(db_session, "server.file.delete")[0].details["recursive"] is True


def test_reads_and_listings_are_not_audited(client, db_session, ready, broker):
    client.get(ready.url + "/files", headers=ready.headers)
    client.get(ready.url + "/files/content", params={"path": "a"}, headers=ready.headers)
    entries = db_session.scalars(
        select(AuditLog).where(AuditLog.action.like("server.file.%"))
    ).all()
    assert entries == []


def test_failed_operations_are_not_audited(client, db_session, ready, broker):
    broker.errors["file.delete"] = "no such file or directory"
    response = client.post(ready.url + "/files/delete", json={"path": "x"}, headers=ready.headers)
    assert response.status_code == 404
    assert _audit(db_session, "server.file.delete") == []


class BlobBroker(FileBroker):
    """Liefert eine Datei stückweise aus dem Speicher, so wie der Agent es tut."""

    def __init__(self, content):
        super().__init__()
        self.content = content

    async def send(self, node_id, action, params, timeout=90):
        self.calls.append((action, params))
        if self.offline:
            raise AgentOffline
        start = params["offset"]
        part = self.content[start : start + params["length"]]
        data = {
            "data": base64.b64encode(part).decode(),
            "size": len(self.content),
            "eof": start + len(part) >= len(self.content),
        }
        return CommandResult(type="result", id="x", ok=True, error=None, data=data)


def _serve(monkeypatch, content):
    fake = BlobBroker(content)
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


def test_download_streams_the_whole_file(client, ready, monkeypatch):
    content = bytes(range(256)) * 200 + b"tail"
    fake = _serve(monkeypatch, content)
    response = client.get(
        ready.url + "/files/download", params={"path": "world/my map.dat"}, headers=ready.headers
    )
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-length"] == str(len(content))
    assert response.headers["content-type"] == "application/octet-stream"
    assert "filename*=UTF-8''my%20map.dat" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert sorted(params["offset"] for _, params in fake.calls) == list(
        range(0, len(content), 512 * 1024)
    )
    assert {action for action, _ in fake.calls} == {"file.read"}


def test_download_of_an_empty_file(client, ready, monkeypatch):
    _serve(monkeypatch, b"")
    response = client.get(
        ready.url + "/files/download", params={"path": "empty.txt"}, headers=ready.headers
    )
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == "0"


def test_download_is_audited_once(client, db_session, ready, monkeypatch):
    _serve(monkeypatch, bytes(20000))
    response = client.get(
        ready.url + "/files/download", params={"path": "a.bin"}, headers=ready.headers
    )
    assert response.status_code == 200
    entries = _audit(db_session, "server.file.download")
    assert len(entries) == 1
    assert entries[0].details["path"] == "a.bin"


def test_download_of_a_directory_is_refused(client, db_session, ready, broker):
    broker.errors["file.read"] = "not a regular file"
    response = client.get(
        ready.url + "/files/download", params={"path": "logs"}, headers=ready.headers
    )
    assert response.status_code == 409
    assert _audit(db_session, "server.file.download") == []


def test_download_with_offline_node_gives_409(client, ready, broker):
    broker.offline = True
    response = client.get(
        ready.url + "/files/download", params={"path": "a.bin"}, headers=ready.headers
    )
    assert response.status_code == 409


def test_download_needs_a_path(client, ready, broker):
    response = client.get(ready.url + "/files/download", headers=ready.headers)
    assert response.status_code == 422
    assert broker.calls == []


def _decompress(client, ready, body):
    return client.post(ready.url + "/files/decompress", json=body, headers=ready.headers)


def test_decompress_passes_the_paths_through(client, ready, broker):
    summary = {"files": 3, "dirs": 1, "skipped": 0, "bytes": 10}
    broker.data["file.decompress"] = summary
    response = _decompress(client, ready, {"path": "a.zip", "to": "out"})
    assert response.status_code == 200, response.text
    assert response.json() == summary
    expected = {"name": _name(ready), "path": "a.zip", "to": "out"}
    assert broker.calls == [("file.decompress", expected)]


def test_decompress_defaults_to_the_archive_folder(client, ready, broker):
    assert _decompress(client, ready, {"path": "sub/a.zip"}).status_code == 200
    assert broker.calls[0][1]["to"] == ""


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ('unsafe path in archive: "../x"', 400),
        ("archive limit exceeded", 413),
        ("invalid archive: zip: not a valid zip file", 422),
        ("unsupported archive type", 400),
        ("openat a.zip: no such file or directory", 404),
        ("not a regular file", 409),
        ("openat link/x: path escapes from parent", 400),
    ],
)
def test_decompress_errors_become_clean_status_codes(client, ready, broker, error, code):
    broker.errors["file.decompress"] = error
    response = _decompress(client, ready, {"path": "a.zip"})
    assert response.status_code == code
    assert response.json()["detail"] != error


def test_decompress_is_blocked_before_the_install_is_done(client, db_session, server, broker):
    _set_status(db_session, server, "installing")
    response = _decompress(client, server, {"path": "a.zip"})
    assert response.status_code == 409
    assert broker.calls == []


def test_decompress_is_audited_only_on_success(client, db_session, ready, broker):
    broker.errors["file.decompress"] = "archive limit exceeded"
    assert _decompress(client, ready, {"path": "a.zip", "to": "out"}).status_code == 413
    assert _audit(db_session, "server.file.decompress") == []
    del broker.errors["file.decompress"]
    broker.data["file.decompress"] = {"files": 2}
    assert _decompress(client, ready, {"path": "a.zip", "to": "out"}).status_code == 200
    entries = _audit(db_session, "server.file.decompress")
    assert len(entries) == 1
    assert entries[0].details["path"] == "a.zip"
    assert entries[0].details["to"] == "out"
    assert entries[0].details["files"] == 2


def test_decompress_gets_a_long_timeout(client, ready, monkeypatch):
    class TimeoutBroker(FileBroker):
        def __init__(self):
            super().__init__()
            self.timeouts = []

        async def send(self, node_id, action, params, timeout=90):
            self.timeouts.append(timeout)
            return await super().send(node_id, action, params, timeout)

    fake = TimeoutBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    assert _decompress(client, ready, {"path": "a.zip"}).status_code == 200
    assert fake.timeouts[0] >= 300


@pytest.mark.parametrize("body", [{"path": "a.zip", "extra": 1}, {"path": "a\x00.zip"}, {}])
def test_decompress_rejects_bad_bodies(client, ready, broker, body):
    assert _decompress(client, ready, body).status_code == 422
    assert broker.calls == []


TRANSFER_ORIGIN = "http://localhost:5183"
TRANSFER_TOKEN = "T" * 43


def _give_node_a_domain(db_session, server, fqdn="node.example.org"):
    node_id = db_session.get(Server, uuid.UUID(server.id)).node_id
    db_session.get(Node, node_id).fqdn = fqdn
    db_session.commit()


def _ticket(client, server, route, headers=None):
    if headers is None:
        headers = {**server.headers, "Origin": TRANSFER_ORIGIN}
    return client.post(
        server.url + "/files/" + route, json={"path": "/a/b.zip"}, headers=headers
    )


@pytest.mark.parametrize(
    ("route", "direction"), [("upload-ticket", "upload"), ("download-ticket", "download")]
)
def test_transfer_ticket_gives_a_direct_url(client, db_session, ready, broker, route, direction):
    _give_node_a_domain(db_session, ready)
    broker.data["transfer.ticket"] = {"token": TRANSFER_TOKEN, "port": 8443, "expires_in": 60}
    response = _ticket(client, ready, route)
    assert response.status_code == 200
    assert response.json() == {
        "direct": True,
        "url": f"https://node.example.org:8443/transfer/{TRANSFER_TOKEN}",
        "expires_in": 60,
    }
    expected = {
        "name": _name(ready),
        "path": "/a/b.zip",
        "direction": direction,
        "origin": TRANSFER_ORIGIN,
    }
    assert broker.calls == [("transfer.ticket", expected)]
    assert _audit(db_session, f"server.file.{direction}")[-1].details["path"] == "/a/b.zip"


def test_transfer_ticket_without_a_domain_falls_back(client, ready, broker):
    response = _ticket(client, ready, "upload-ticket")
    assert response.status_code == 200
    assert response.json() == {"direct": False}
    assert broker.calls == []


def test_transfer_ticket_without_an_origin_falls_back(client, db_session, ready, broker):
    _give_node_a_domain(db_session, ready)
    response = _ticket(client, ready, "upload-ticket", headers=ready.headers)
    assert response.json() == {"direct": False}
    assert broker.calls == []


@pytest.mark.parametrize(
    "error", ['unknown action "transfer.ticket"', "transfers are not enabled on this node"]
)
def test_transfer_ticket_falls_back_on_agent_answer(client, db_session, ready, broker, error):
    _give_node_a_domain(db_session, ready)
    broker.errors["transfer.ticket"] = error
    assert _ticket(client, ready, "upload-ticket").json() == {"direct": False}
    assert _audit(db_session, "server.file.upload") == []


def test_transfer_ticket_for_a_missing_file_is_404(client, db_session, ready, broker):
    _give_node_a_domain(db_session, ready)
    broker.errors["transfer.ticket"] = "no such file or directory"
    assert _ticket(client, ready, "download-ticket").status_code == 404
    assert _audit(db_session, "server.file.download") == []


def test_transfer_ticket_rejects_an_invalid_agent_answer(client, db_session, ready, broker):
    _give_node_a_domain(db_session, ready)
    broker.data["transfer.ticket"] = {"token": "short", "port": 8443}
    assert _ticket(client, ready, "upload-ticket").status_code == 502
    assert _audit(db_session, "server.file.upload") == []


@pytest.mark.parametrize("state", ["new", "installing"])
def test_transfer_ticket_is_blocked_before_the_install_is_done(
    client, db_session, server, broker, state
):
    _set_status(db_session, server, state)
    _give_node_a_domain(db_session, server)
    assert _ticket(client, server, "upload-ticket").status_code == 409
    assert broker.calls == []
