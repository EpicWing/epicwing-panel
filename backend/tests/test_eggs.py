import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.factories import egg_body, make_egg, make_nest
from tests.test_nodes_detail import _login


def test_endpoints_require_login():
    anonymous = TestClient(app)
    assert anonymous.get("/api/nests").status_code == 401
    assert anonymous.get("/api/eggs").status_code == 401


def test_nest_lifecycle(client, user):
    headers = _login(client, user)
    nest_id = make_nest(client, headers, "Games")
    assert client.get("/api/nests").json()[0]["egg_count"] == 0

    changed = client.patch(
        f"/api/nests/{nest_id}", json={"description": "Steam and co."}, headers=headers
    )
    assert changed.status_code == 200
    assert changed.json()["description"] == "Steam and co."
    assert changed.json()["name"] == "Games"

    assert client.delete(f"/api/nests/{nest_id}", headers=headers).status_code == 204
    assert client.get("/api/nests").json() == []


def test_nest_names_are_unique_ignoring_case(client, user):
    headers = _login(client, user)
    make_nest(client, headers, "Games")
    second = make_nest(client, headers, "Web")
    assert client.post("/api/nests", json={"name": "GAMES"}, headers=headers).status_code == 409
    url = f"/api/nests/{second}"
    assert client.patch(url, json={"name": "games"}, headers=headers).status_code == 409
    assert client.patch(url, json={"name": "WEB"}, headers=headers).status_code == 200


def test_nest_with_eggs_cannot_be_deleted(client, user):
    headers = _login(client, user)
    nest_id = make_nest(client, headers)
    egg_id = make_egg(client, headers, nest_id)
    assert client.delete(f"/api/nests/{nest_id}", headers=headers).status_code == 409
    assert client.delete(f"/api/eggs/{egg_id}", headers=headers).status_code == 204
    assert client.delete(f"/api/nests/{nest_id}", headers=headers).status_code == 204


def test_egg_is_returned_with_variables(client, user):
    headers = _login(client, user)
    nest_id = make_nest(client, headers)
    egg_id = make_egg(client, headers, nest_id)

    egg = client.get(f"/api/eggs/{egg_id}").json()
    assert egg["nest_name"] == "Games"
    assert egg["docker_image"] == "nginx:1.27-alpine"
    assert {v["env_variable"] for v in egg["variables"]} == {"SERVER_NAME", "MOTD"}

    assert [e["id"] for e in client.get("/api/eggs").json()] == [egg_id]
    assert [e["id"] for e in client.get(f"/api/eggs?nest_id={nest_id}").json()] == [egg_id]
    assert client.get(f"/api/eggs?nest_id={uuid.uuid4()}").json() == []


def test_egg_names_are_unique_per_nest(client, user):
    headers = _login(client, user)
    games = make_nest(client, headers, "Games")
    web = make_nest(client, headers, "Web")
    make_egg(client, headers, games, "Nginx")
    response = client.post("/api/eggs", json=egg_body(games, "nginx"), headers=headers)
    assert response.status_code == 409
    make_egg(client, headers, web, "Nginx")


def test_egg_update_replaces_variables(client, user):
    headers = _login(client, user)
    egg_id = make_egg(client, headers, make_nest(client, headers))
    url = f"/api/eggs/{egg_id}"
    response = client.patch(
        url,
        json={
            "startup": "nginx",
            "variables": [{"name": "Port", "env_variable": "PORT", "default_value": "80"}],
        },
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["startup"] == "nginx"
    assert body["docker_image"] == "nginx:1.27-alpine"
    assert [v["env_variable"] for v in body["variables"]] == ["PORT"]
    assert client.patch(url, json={"name": None}, headers=headers).status_code == 422


def test_unknown_references_give_404(client, user):
    headers = _login(client, user)
    response = client.post("/api/eggs", json=egg_body(str(uuid.uuid4())), headers=headers)
    assert response.status_code == 404
    assert client.get(f"/api/eggs/{uuid.uuid4()}").status_code == 404
    assert client.delete(f"/api/nests/{uuid.uuid4()}", headers=headers).status_code == 404


def test_csrf_token_is_required(client, user):
    _login(client, user)
    assert client.post("/api/nests", json={"name": "Games"}).status_code == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"docker_image": "-rm"},
        {"docker_image": "Nginx"},
        {"startup": "a\nb"},
        {"stop_command": "x" * 256},
        {"name": ""},
        {"privileged": True},
        {"install_script": "echo\x00"},
        {"variables": [{"name": "A", "env_variable": "bad-name"}]},
        {"variables": [{"name": "A", "env_variable": "A"}, {"name": "B", "env_variable": "A"}]},
    ],
)
def test_invalid_egg_input_is_rejected(client, user, changes):
    headers = _login(client, user)
    nest_id = make_nest(client, headers)
    response = client.post("/api/eggs", json=egg_body(nest_id, **changes), headers=headers)
    assert response.status_code == 422


def _plain_user(db_session):
    from app.models import Role, RolePermission, User, UserRole
    from app.security.passwords import hash_password
    from app.security.permissions import Permission

    account = User(
        email="plain@example.test",
        password_hash=hash_password("correct-horse-battery"),
        is_admin=False,
    )
    db_session.add(account)
    role = Role(name="node-operator", scope="global")
    db_session.add(role)
    db_session.flush()
    db_session.add(RolePermission(role_id=role.id, permission=Permission.NODES_MANAGE.value))
    db_session.add(UserRole(user_id=account.id, role_id=role.id))
    db_session.commit()
    return account


def test_egg_writing_requires_an_admin(client, db_session, user):
    plain = _plain_user(db_session)
    headers = _login(client, plain)
    nest_id = make_nest(client, headers)
    assert client.post("/api/eggs", json=egg_body(nest_id), headers=headers).status_code == 403
    egg_id = make_egg(client, _login(client, user), nest_id)
    changed = client.patch(f"/api/eggs/{egg_id}", json={"name": "X"}, headers=headers)
    assert changed.status_code == 403
    assert client.delete(f"/api/eggs/{egg_id}", headers=headers).status_code == 403
