from types import SimpleNamespace

import pytest

from tests.factories import egg_body, make_allocations, make_egg, make_nest
from tests.test_nodes_detail import _create, _login

STARTUP = "run --slots {{MAX_PLAYERS}} --port {{SERVER_PORT}} --mem {{SERVER_MEMORY}}M"
VARIABLES = [
    {
        "name": "Max players",
        "env_variable": "MAX_PLAYERS",
        "default_value": "20",
        "rules": "required|integer|between:1,100",
    },
    {
        "name": "Mode",
        "env_variable": "MODE",
        "default_value": "easy",
        "rules": "required|in:easy,hard",
    },
]


@pytest.fixture
def env(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers)
    nest_id = make_nest(client, headers)
    return SimpleNamespace(
        headers=headers,
        user=user,
        node_id=node_id,
        nest_id=nest_id,
        egg_id=make_egg(client, headers, nest_id, "Game", startup=STARTUP, variables=VARIABLES),
        allocations=make_allocations(client, headers, node_id, 25001, 25002),
    )


def _post(client, env, **changes):
    body = {
        "name": "Game 1",
        "owner_id": str(env.user.id),
        "node_id": env.node_id,
        "egg_id": env.egg_id,
        "allocation_id": env.allocations[0],
    }
    body.update(changes)
    return client.post("/api/servers", json=body, headers=env.headers)


def _no_server_and_free_ports(client, env):
    assert client.get("/api/servers").json() == []
    rows = client.get(f"/api/nodes/{env.node_id}/allocations").json()
    assert all(r["server_id"] is None for r in rows)


def test_startup_command_is_rendered(client, env):
    body = _post(client, env, variables={"MAX_PLAYERS": "50"}, memory_mb=2048).json()
    assert body["startup"] == STARTUP
    assert body["startup_command"] == "run --slots 50 --port 25001 --mem 2048M"
    listed = client.get("/api/servers").json()[0]
    assert listed["startup_command"] == body["startup_command"]


@pytest.mark.parametrize(
    "variables",
    [
        {"MAX_PLAYERS": "500"},
        {"MAX_PLAYERS": "x"},
        {"MAX_PLAYERS": ""},
        {"MODE": "other"},
    ],
)
def test_values_must_match_the_rules(client, env, variables):
    assert _post(client, env, variables=variables).status_code == 422
    _no_server_and_free_ports(client, env)


def test_required_variable_without_default_must_be_given(client, env):
    token = {"name": "Token", "env_variable": "TOKEN", "rules": "required|string"}
    egg_id = make_egg(client, env.headers, env.nest_id, "Needs token", variables=[token])
    assert _post(client, env, egg_id=egg_id).status_code == 422
    _no_server_and_free_ports(client, env)
    assert _post(client, env, egg_id=egg_id, variables={"TOKEN": "abc"}).status_code == 201


def test_update_checks_the_rules(client, env):
    server_id = _post(client, env).json()["id"]
    url = f"/api/servers/{server_id}"
    too_small = client.patch(url, json={"variables": {"MAX_PLAYERS": "0"}}, headers=env.headers)
    assert too_small.status_code == 422
    response = client.patch(url, json={"variables": {"MAX_PLAYERS": "5"}}, headers=env.headers)
    assert response.status_code == 200
    assert response.json()["startup_command"] == "run --slots 5 --port 25001 --mem 1024M"


def test_egg_rules_are_checked(client, user):
    headers = _login(client, user)
    nest_id = make_nest(client, headers)
    bad = [
        {"name": "A", "env_variable": "A", "rules": "bogus"},
        {"name": "A", "env_variable": "A", "rules": "between:5,1"},
        {"name": "A", "env_variable": "A", "default_value": "abc", "rules": "integer"},
    ]
    for variable in bad:
        body = egg_body(nest_id, variables=[variable])
        assert client.post("/api/eggs", json=body, headers=headers).status_code == 422, variable


def test_variable_visibility_and_rules_are_stored(client, user):
    headers = _login(client, user)
    variable = {
        "name": "A",
        "env_variable": "A",
        "default_value": "1",
        "rules": "required|integer",
        "user_viewable": False,
        "user_editable": False,
    }
    body = egg_body(make_nest(client, headers), variables=[variable])
    saved = client.post("/api/eggs", json=body, headers=headers).json()["variables"][0]
    assert saved["rules"] == "required|integer"
    assert saved["user_viewable"] is False
    assert saved["user_editable"] is False


def test_unknown_placeholders_are_rejected(client, user):
    headers = _login(client, user)
    nest_id = make_nest(client, headers)
    for startup in ("run {{NOPE}}", "run {{SERVER_NAME}} {{MAX}}"):
        body = egg_body(nest_id, startup=startup)
        assert client.post("/api/eggs", json=body, headers=headers).status_code == 422
    good = egg_body(nest_id, startup="run {{SERVER_NAME}} {{SERVER_PORT}} {{ env.MOTD }}")
    egg_id = client.post("/api/eggs", json=good, headers=headers).json()["id"]
    url = f"/api/eggs/{egg_id}"
    assert client.patch(url, json={"startup": "x {{NOPE}}"}, headers=headers).status_code == 422
    assert client.patch(url, json={"startup": "x {{MOTD}}"}, headers=headers).status_code == 200
