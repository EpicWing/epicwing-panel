import importlib
from types import SimpleNamespace

import pytest

from app.agentlink.protocol import CommandResult
from tests.factories import make_allocations, make_egg, make_nest
from tests.test_nodes_detail import _create, _login
from tests.test_server_power import FakeBroker

IP = "45.142.104.41"


@pytest.fixture
def env(client, user, monkeypatch):
    broker = FakeBroker()
    monkeypatch.setattr(importlib.import_module("app.api.servers"), "broker", broker)
    headers = _login(client, user)
    node_id = _create(client, headers)
    nest_id = make_nest(client, headers)
    egg_id = make_egg(client, headers, nest_id, startup="run {{SERVER_PORT}}")
    ids = make_allocations(client, headers, node_id, 25001, 25020)
    body = {
        "name": "Game 1",
        "owner_id": str(user.id),
        "node_id": node_id,
        "egg_id": egg_id,
        "allocation_id": ids[0],
    }
    created = client.post("/api/servers", json=body, headers=headers)
    assert created.status_code == 201, created.text
    url = f"/api/servers/{created.json()['id']}"
    result = SimpleNamespace(client=client, headers=headers, broker=broker, url=url, ids=ids)
    assert _ports(result) == [25001]
    return result


def _get(env, path=""):
    return env.client.get(env.url + path)


def _ports(env):
    return [a["port"] for a in _get(env, "/allocations").json()]


def _free_ports(env):
    return [a["port"] for a in _get(env, "/allocations/free").json()]


def _free_id(env, port):
    rows = _get(env, "/allocations/free").json()
    return next(a["id"] for a in rows if a["port"] == port)


def _add(env, port):
    body = {"allocation_id": _free_id(env, port)}
    return env.client.post(env.url + "/allocations", json=body, headers=env.headers)


def _remove(env, allocation_id):
    return env.client.delete(env.url + f"/allocations/{allocation_id}", headers=env.headers)


def _make_primary(env, allocation_id):
    return env.client.put(env.url + f"/allocations/{allocation_id}/primary", headers=env.headers)


def _install(env):
    response = env.client.post(env.url + "/install", headers=env.headers)
    assert response.status_code == 200, response.text
    env.broker.calls.clear()


def _status(env):
    return _get(env).json()["status"]


def _fail_next_create(broker):
    """Das nächste container.create scheitert, danach klappt wieder alles."""
    original = broker.send
    state = {"armed": True}

    async def send(node_id, action, params, timeout=90):
        if action == "container.create" and state["armed"]:
            state["armed"] = False
            broker.calls.append((action, params))
            return CommandResult(type="result", id="x", ok=False, error="boom", data={})
        return await original(node_id, action, params, timeout)

    broker.send = send


def test_add_before_install_only_changes_the_database(env):
    response = _add(env, 25002)
    assert response.status_code == 201, response.text
    assert [a["port"] for a in response.json()] == [25001, 25002]
    assert response.json()[0]["is_primary"] is True
    assert env.broker.calls == []
    assert 25002 not in _free_ports(env)
    assert 25003 in _free_ports(env)


def test_add_recreates_the_container_with_the_new_ports(env):
    _install(env)
    assert _add(env, 25002).status_code == 201
    assert env.broker.actions() == ["container.remove", "container.create"]
    params = env.broker.calls[1][1]
    ports = {(p["host"], p["proto"], p["ip"]) for p in params["ports"]}
    assert ports == {(port, proto, IP) for port in (25001, 25002) for proto in ("tcp", "udp")}
    assert params["env"]["SERVER_PORT"] == "25001"
    assert "install_script" not in params
    assert _status(env) == "offline"


def test_remove_frees_the_allocation_and_recreates_the_container(env):
    _install(env)
    assert _add(env, 25002).status_code == 201
    env.broker.calls.clear()
    second = next(a["id"] for a in _get(env, "/allocations").json() if a["port"] == 25002)
    assert _remove(env, second).status_code == 204
    assert _ports(env) == [25001]
    assert 25002 in _free_ports(env)
    assert env.broker.actions() == ["container.remove", "container.create"]
    assert {p["host"] for p in env.broker.calls[1][1]["ports"]} == {25001}


def test_primary_allocation_cannot_be_removed(env):
    primary = _get(env, "/allocations").json()[0]["id"]
    assert _remove(env, primary).status_code == 409
    assert _ports(env) == [25001]


def test_set_primary_changes_the_server_port(env):
    _install(env)
    assert _add(env, 25002).status_code == 201
    second = next(a["id"] for a in _get(env, "/allocations").json() if a["port"] == 25002)
    env.broker.calls.clear()
    response = _make_primary(env, second)
    assert response.status_code == 200, response.text
    assert [a["port"] for a in response.json()] == [25002, 25001]
    assert response.json()[0]["is_primary"] is True
    assert env.broker.calls[-1][1]["env"]["SERVER_PORT"] == "25002"
    env.broker.calls.clear()
    assert _make_primary(env, second).status_code == 200
    assert env.broker.calls == []


def test_no_change_while_the_server_runs(env):
    _install(env)
    power = env.client.post(env.url + "/power", json={"action": "start"}, headers=env.headers)
    assert power.status_code == 200, power.text
    env.broker.calls.clear()
    assert _add(env, 25002).status_code == 409
    assert _ports(env) == [25001]
    assert env.broker.calls == []


def test_failed_create_restores_the_old_container(env):
    _install(env)
    _fail_next_create(env.broker)
    assert _add(env, 25002).status_code == 502
    assert _ports(env) == [25001]
    assert env.broker.actions() == ["container.remove", "container.create", "container.create"]
    assert {p["host"] for p in env.broker.calls[2][1]["ports"]} == {25001}
    assert _status(env) == "offline"


def test_failed_restore_marks_the_server_as_error(env):
    _install(env)
    env.broker.errors["container.create"] = "boom"
    assert _add(env, 25002).status_code == 502
    assert _ports(env) == [25001]
    detail = _get(env).json()
    assert detail["status"] == "error"
    assert "Reinstall" in detail["last_error"]


def test_failed_remove_changes_nothing(env):
    _install(env)
    env.broker.errors["container.remove"] = "boom"
    assert _add(env, 25002).status_code == 502
    assert _ports(env) == [25001]
    assert env.broker.actions() == ["container.remove"]
    assert _status(env) == "offline"


def test_offline_node_changes_nothing(env):
    _install(env)
    env.broker.offline = True
    assert _add(env, 25002).status_code == 409
    assert _ports(env) == [25001]
    assert _status(env) == "offline"


def test_unknown_and_foreign_allocations_are_rejected(env):
    unknown = "00000000-0000-4000-8000-000000000000"
    response = env.client.post(
        env.url + "/allocations", json={"allocation_id": unknown}, headers=env.headers
    )
    assert response.status_code == 422
    own = _get(env, "/allocations").json()[0]["id"]
    again = env.client.post(
        env.url + "/allocations", json={"allocation_id": own}, headers=env.headers
    )
    assert again.status_code == 409
    assert _remove(env, env.ids[5]).status_code == 404


def test_at_most_16_allocations(env):
    for port in range(25002, 25017):
        assert _add(env, port).status_code == 201
    assert len(_ports(env)) == 16
    assert _add(env, 25017).status_code == 409
    assert len(_ports(env)) == 16
