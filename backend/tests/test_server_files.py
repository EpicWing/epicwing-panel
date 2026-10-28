import importlib
import uuid

import pytest

from app.agentlink.commands import AgentOffline
from app.agentlink.protocol import CommandResult
from app.models import Server
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
        {"path": "a", "data": "A" * 12_001},
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
