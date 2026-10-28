import copy

import pytest

from tests.factories import make_nest
from tests.test_egg_io import PTDL
from tests.test_nodes_detail import _login


def _import(client, headers, nest_id, egg=None):
    body = {"nest_id": nest_id, "egg": PTDL if egg is None else egg}
    return client.post("/api/eggs/import", json=body, headers=headers)


def test_import_creates_the_egg(client, user):
    headers = _login(client, user)
    nest_id = make_nest(client, headers)
    response = _import(client, headers, nest_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Test Game"
    assert body["docker_image"] == "ghcr.io/pterodactyl/yolks:java_17"
    assert body["install_script"] == "#!/bin/bash\necho hi"
    assert body["stop_command"] == "stop"
    rules = {v["env_variable"]: v["rules"] for v in body["variables"]}
    assert rules["MAX_PLAYERS"] == "required|integer"
    assert body["warnings"]
    assert [e["name"] for e in client.get("/api/eggs").json()] == ["Test Game"]


def test_import_warns_about_unknown_placeholders(client, user):
    headers = _login(client, user)
    egg = copy.deepcopy(PTDL)
    egg["startup"] = "run {{server.build.env.FOO}}"
    response = _import(client, headers, make_nest(client, headers), egg)
    assert response.status_code == 201
    assert any("server.build.env.FOO" in w for w in response.json()["warnings"])


def test_import_twice_gives_409(client, user):
    headers = _login(client, user)
    nest_id = make_nest(client, headers)
    assert _import(client, headers, nest_id).status_code == 201
    assert _import(client, headers, nest_id).status_code == 409


def test_import_into_unknown_nest_gives_404(client, user):
    headers = _login(client, user)
    response = _import(client, headers, "00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"meta": {"version": "other"}},
        {"docker_images": {"x": "-rm"}},
        {"docker_images": {}},
        {"startup": "x" * 3000},
    ],
)
def test_bad_files_are_rejected(client, user, change):
    headers = _login(client, user)
    egg = {**copy.deepcopy(PTDL), **change}
    response = _import(client, headers, make_nest(client, headers), egg)
    assert response.status_code == 422
    assert client.get("/api/eggs").json() == []


def test_export_and_import_again(client, user):
    headers = _login(client, user)
    egg_id = _import(client, headers, make_nest(client, headers)).json()["id"]
    exported = client.get(f"/api/eggs/{egg_id}/export")
    assert exported.status_code == 200
    data = exported.json()
    assert data["meta"] == {"version": "PTDL_v2"}
    assert data["config"]["stop"] == "stop"
    assert data["config"]["startup"] == PTDL["config"]["startup"]
    assert data["scripts"]["installation"]["container"] == "alpine:3.4"
    assert {v["env_variable"] for v in data["variables"]} == {"SERVER_JARFILE", "MAX_PLAYERS"}

    other = make_nest(client, headers, "Other")
    again = _import(client, headers, other, data)
    assert again.status_code == 201, again.text
    assert again.json()["warnings"] == []


def test_export_of_unknown_egg_gives_404(client, user):
    _login(client, user)
    response = client.get("/api/eggs/00000000-0000-0000-0000-000000000000/export")
    assert response.status_code == 404
