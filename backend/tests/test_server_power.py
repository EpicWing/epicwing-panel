import importlib
import uuid
from types import SimpleNamespace

import pytest

from app.agentlink.commands import AgentOffline
from app.agentlink.protocol import CommandResult
from app.services import lifecycle
from tests.factories import make_allocations, make_egg, make_nest
from tests.test_nodes_detail import _create, _login


class FakeBroker:
    def __init__(self):
        self.calls = []
        self.errors = {}
        self.offline = False

    async def send(self, node_id, action, params, timeout=90):
        self.calls.append((action, params))
        if self.offline:
            raise AgentOffline
        error = self.errors.get(action)
        return CommandResult(type="result", id="x", ok=error is None, error=error, data={})

    def actions(self):
        return [action for action, _ in self.calls]


@pytest.fixture
def broker(monkeypatch):
    fake = FakeBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", fake)
    return fake


@pytest.fixture
def server(client, user, broker):
    headers = _login(client, user)
    node_id = _create(client, headers)
    nest_id = make_nest(client, headers)
    egg_id = make_egg(client, headers, nest_id, startup="run {{SERVER_PORT}}")
    allocations = make_allocations(client, headers, node_id, 25001, 25001)
    body = {
        "name": "Game 1",
        "owner_id": str(user.id),
        "node_id": node_id,
        "egg_id": egg_id,
        "allocation_id": allocations[0],
    }
    created = client.post("/api/servers", json=body, headers=headers).json()
    return SimpleNamespace(id=created["id"], headers=headers, url=f"/api/servers/{created['id']}")


def _post(client, server, path, body=None):
    return client.post(server.url + path, json=body, headers=server.headers)


def _power(client, server, action):
    return _post(client, server, "/power", {"action": action})


def _status(client, server):
    return client.get(server.url).json()["status"]


def test_install_creates_the_container(client, server, broker):
    response = _post(client, server, "/install")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "offline"
    assert broker.actions() == ["container.create"]
    params = broker.calls[0][1]
    assert params["name"] == server.id
    assert params["data"] is True
    assert params["env"]["STARTUP"] == "run {{SERVER_PORT}}"
    assert params["env"]["SERVER_PORT"] == "25001"
    assert params["env"]["SERVER_MEMORY"] == "1024"
    assert params["env"]["SERVER_NAME"] == "My Server"
    assert {(p["host"], p["proto"]) for p in params["ports"]} == {(25001, "tcp"), (25001, "udp")}


def test_start_stop_and_kill(client, server, broker):
    _post(client, server, "/install")
    assert _power(client, server, "start").json()["status"] == "running"
    assert _power(client, server, "stop").json()["status"] == "offline"
    assert _power(client, server, "start").json()["status"] == "running"
    assert _power(client, server, "kill").json()["status"] == "offline"
    assert broker.actions() == [
        "container.create",
        "container.start",
        "container.stop",
        "container.start",
        "container.kill",
    ]


def test_actions_in_the_wrong_state_are_refused(client, server, broker):
    assert _power(client, server, "start").status_code == 409
    assert _post(client, server, "/install").status_code == 200
    assert _power(client, server, "stop").status_code == 409
    assert _power(client, server, "start").status_code == 200
    assert _post(client, server, "/install").status_code == 409
    assert len(broker.calls) == 2


def test_unknown_power_action_is_rejected(client, server):
    assert _power(client, server, "reboot").status_code == 422


def test_agent_error_sets_the_error_state(client, server, broker):
    broker.errors["container.create"] = "boom"
    response = _post(client, server, "/install")
    assert response.status_code == 502
    assert response.json()["detail"] == "boom"
    body = client.get(server.url).json()
    assert (body["status"], body["last_error"]) == ("error", "boom")
    del broker.errors["container.create"]
    assert _post(client, server, "/install").json()["status"] == "offline"
    assert client.get(server.url).json()["last_error"] is None


def test_offline_node_gives_409(client, server, broker):
    broker.offline = True
    response = _post(client, server, "/install")
    assert response.status_code == 409
    assert _status(client, server) == "error"


def test_reinstall_replaces_the_container(client, server, broker):
    _post(client, server, "/install")
    assert _post(client, server, "/install").status_code == 200
    assert broker.actions() == ["container.create", "container.remove", "container.create"]


def test_reinstall_accepts_a_missing_container(client, server, broker):
    _post(client, server, "/install")
    broker.errors["container.remove"] = "docker inspect: Error: No such object: x"
    assert _post(client, server, "/install").status_code == 200


def test_delete_removes_the_container(client, server, broker):
    _post(client, server, "/install")
    assert client.delete(server.url, headers=server.headers).status_code == 204
    assert broker.actions()[-1] == "container.remove"


def test_delete_of_a_new_server_does_not_call_the_agent(client, server, broker):
    assert client.delete(server.url, headers=server.headers).status_code == 204
    assert broker.calls == []


def test_delete_works_when_the_node_is_offline(client, server, broker):
    _post(client, server, "/install")
    broker.offline = True
    assert client.delete(server.url, headers=server.headers).status_code == 204


def test_delete_stops_on_a_real_agent_error(client, server, broker):
    _post(client, server, "/install")
    broker.errors["container.remove"] = "permission denied"
    assert client.delete(server.url, headers=server.headers).status_code == 502
    assert client.get(server.url).status_code == 200


def test_build_spec_protects_reserved_names():
    server = SimpleNamespace(
        id=uuid.uuid4(), image="img:1", startup="x", memory_mb=0, cpus=0
    )
    allocations = [SimpleNamespace(ip="1.2.3.4", port=7777)]
    variables = {"STARTUP": "evil", "SERVER_PORT": "1", "A": "b"}
    spec = lifecycle.build_spec(server, allocations, variables, 8192)
    assert spec["env"] == {
        "A": "b",
        "STARTUP": "x",
        "SERVER_MEMORY": "8192",
        "SERVER_IP": "1.2.3.4",
        "SERVER_PORT": "7777",
    }
    assert (spec["memory_mb"], spec["cpus"]) == (0, 0)


def test_build_spec_without_startup_leaves_the_image_default():
    server = SimpleNamespace(id=uuid.uuid4(), image="img:1", startup="", memory_mb=512, cpus=1)
    assert "STARTUP" not in lifecycle.build_spec(server, [], {}, None)["env"]
