import asyncio
import importlib
import uuid
from types import SimpleNamespace

import pytest

from app.agentlink.commands import AgentOffline
from app.agentlink.protocol import CommandResult
from app.models import Egg, Server
from app.services import lifecycle
from tests.factories import make_allocations, make_egg, make_nest
from tests.test_nodes_detail import _create, _login


class FakeBroker:
    def __init__(self):
        self.calls = []
        self.errors = {}
        self.offline = False
        self.timeouts = set()
        self.timeouts_seen = []

    async def send(self, node_id, action, params, timeout=90):
        self.calls.append((action, params))
        self.timeouts_seen.append(timeout)
        if self.offline:
            raise AgentOffline
        if action in self.timeouts:
            raise TimeoutError
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
    assert _power(client, server, "start").json()["status"] == "starting"
    assert _power(client, server, "stop").json()["status"] == "offline"
    assert _power(client, server, "start").json()["status"] == "starting"
    assert _power(client, server, "kill").json()["status"] == "offline"
    # Jeder Start erzeugt den Container aus dem aktuellen Stand neu.
    assert broker.actions() == [
        "container.create",
        "container.remove",
        "container.create",
        "container.start",
        "container.stop",
        "container.remove",
        "container.create",
        "container.start",
        "container.kill",
    ]


def test_actions_in_the_wrong_state_are_refused(client, server, broker):
    assert _power(client, server, "start").status_code == 409
    assert _post(client, server, "/install").status_code == 200
    assert _power(client, server, "stop").status_code == 409
    assert _power(client, server, "start").status_code == 200
    assert _post(client, server, "/install").status_code == 409
    assert len(broker.calls) == 4


def test_unknown_power_action_is_rejected(client, server):
    assert _power(client, server, "reboot").status_code == 422


def test_agent_error_sets_the_error_state(client, server, broker):
    broker.errors["container.create"] = "boom"
    response = _post(client, server, "/install")
    assert response.status_code == 502
    # Raw agent texts do not go to users, only to the log and the audit log.
    assert response.json()["detail"] == "Something went wrong. Please try again or contact support."
    body = client.get(server.url).json()
    assert (body["status"], body["last_error"]) == (
        "error",
        "Something went wrong. Please try again or contact support.",
    )
    del broker.errors["container.create"]
    assert _post(client, server, "/install").json()["status"] == "offline"
    assert client.get(server.url).json()["last_error"] is None


def test_install_timeout_keeps_installing(client, server, broker):
    egg_id = client.get(server.url).json()["egg_id"]
    script = client.patch(
        f"/api/eggs/{egg_id}", json={"install_script": "sleep 1"}, headers=server.headers
    )
    assert script.status_code == 200
    broker.timeouts.add("container.install")
    response = _post(client, server, "/install")
    assert response.status_code == 504
    assert _status(client, server) == "installing"
    install_index = [c[0] for c in broker.calls].index("container.install")
    assert broker.timeouts_seen[install_index] > 90


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
    server = SimpleNamespace(id=uuid.uuid4(), image="img:1", startup="x", memory_mb=0, cpus=0)
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


def test_restart_stops_then_starts(client, server, broker):
    _post(client, server, "/install")
    _power(client, server, "start")
    broker.calls.clear()
    response = _power(client, server, "restart")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "starting"
    assert broker.actions() == [
        "container.stop",
        "container.remove",
        "container.create",
        "container.start",
    ]


def test_restart_reports_stopping_while_the_container_stops(client, server, broker, db_session):
    _post(client, server, "/install")
    _power(client, server, "start")
    seen = []
    original = broker.send

    async def spy(node_id, action, params, timeout=90):
        seen.append((action, db_session.get(Server, uuid.UUID(server.id)).status))
        return await original(node_id, action, params, timeout)

    broker.send = spy
    assert _power(client, server, "restart").status_code == 200
    assert seen == [
        ("container.stop", "stopping"),
        ("container.remove", "starting"),
        ("container.create", "starting"),
        ("container.start", "starting"),
    ]


def test_offline_node_keeps_the_status(client, server, broker):
    _post(client, server, "/install")
    _power(client, server, "start")
    broker.offline = True
    response = _power(client, server, "restart")
    assert response.status_code == 409
    assert response.json()["detail"] == "The node is offline."
    body = client.get(server.url).json()
    assert (body["status"], body["last_error"]) == ("starting", None)


def test_second_action_is_refused_while_one_runs(client, server, broker):
    _post(client, server, "/install")
    _power(client, server, "start")
    module = importlib.import_module("app.api.servers")
    lock = asyncio.Lock()
    asyncio.run(lock.acquire())
    module._locks[uuid.UUID(server.id)] = lock
    try:
        assert _power(client, server, "restart").status_code == 409
        assert _power(client, server, "stop").status_code == 409
        assert _power(client, server, "kill").status_code == 200
    finally:
        module._locks.pop(uuid.UUID(server.id), None)


def _set_stop_command(db_session, server, command):
    row = db_session.get(Server, uuid.UUID(server.id))
    egg = db_session.get(Egg, row.egg_id)
    egg.stop_command = command
    db_session.commit()


def _running(client, server):
    _post(client, server, "/install")
    assert _power(client, server, "start").json()["status"] == "starting"


def test_stop_sends_the_egg_stop_command(client, server, broker, db_session):
    _running(client, server)
    _set_stop_command(db_session, server, "EXIT")
    broker.calls.clear()
    assert _power(client, server, "stop").json()["status"] == "offline"
    assert broker.calls == [("container.stop", {"name": server.id, "command": "EXIT"})]


def test_stop_without_stop_command_sends_only_the_name(client, server, broker, db_session):
    _running(client, server)
    _set_stop_command(db_session, server, "")
    broker.calls.clear()
    assert _power(client, server, "stop").status_code == 200
    assert broker.calls == [("container.stop", {"name": server.id})]


def test_restart_sends_the_stop_command_then_starts(client, server, broker, db_session):
    _running(client, server)
    _set_stop_command(db_session, server, "EXIT")
    broker.calls.clear()
    assert _power(client, server, "restart").status_code == 200
    assert broker.actions() == [
        "container.stop",
        "container.remove",
        "container.create",
        "container.start",
    ]
    assert broker.calls[0] == ("container.stop", {"name": server.id, "command": "EXIT"})
    assert broker.calls[-1] == ("container.start", {"name": server.id})


def test_kill_never_sends_the_stop_command(client, server, broker, db_session):
    _running(client, server)
    _set_stop_command(db_session, server, "EXIT")
    broker.calls.clear()
    assert _power(client, server, "kill").status_code == 200
    assert broker.calls == [("container.kill", {"name": server.id})]


def test_start_never_sends_the_stop_command(client, server, broker, db_session):
    _post(client, server, "/install")
    _set_stop_command(db_session, server, "EXIT")
    broker.calls.clear()
    assert _power(client, server, "start").status_code == 200
    assert broker.actions() == ["container.remove", "container.create", "container.start"]
    assert all("command" not in (params or {}) for _, params in broker.calls)


def test_stop_command_is_trimmed(client, server, broker, db_session):
    _running(client, server)
    _set_stop_command(db_session, server, "  EXIT  ")
    broker.calls.clear()
    assert _power(client, server, "stop").status_code == 200
    assert broker.calls[0][1]["command"] == "EXIT"


def test_server_can_be_renamed(client, server):
    response = client.patch(server.url, json={"name": "Renamed Game"}, headers=server.headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Game"
    assert client.get(server.url).json()["name"] == "Renamed Game"


def test_rename_rejects_empty_and_null_names(client, server):
    for bad in ("", "   ", None):
        response = client.patch(server.url, json={"name": bad}, headers=server.headers)
        assert response.status_code == 422, repr(bad)
    assert client.get(server.url).json()["name"] == "Game 1"


def test_start_recreates_the_container_from_the_current_state(client, server, broker):
    _post(client, server, "/install")
    broker.calls.clear()
    assert _power(client, server, "start").status_code == 200
    action, params = broker.calls[1]
    assert action == "container.create"
    assert params["name"] == server.id
    assert params["env"]["SERVER_PORT"] == "25001"
