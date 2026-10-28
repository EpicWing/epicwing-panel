import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import AuditLog, Server
from tests.factories import make_allocations, make_egg, make_nest
from tests.test_nodes_detail import _create, _login


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
        egg_id=make_egg(client, headers, nest_id),
        allocations=make_allocations(client, headers, node_id, 25001, 25003),
    )


def _post(client, env, **changes):
    body = {
        "name": "Web 1",
        "owner_id": str(env.user.id),
        "node_id": env.node_id,
        "egg_id": env.egg_id,
        "allocation_id": env.allocations[0],
    }
    body.update(changes)
    return client.post("/api/servers", json=body, headers=env.headers)


def test_create_claims_allocations_and_fills_defaults(client, env):
    response = _post(
        client, env, extra_allocation_ids=[env.allocations[1]], variables={"MOTD": "Hi"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "new"
    assert body["image"] == "nginx:1.27-alpine"
    assert body["startup"] == "nginx -g 'daemon off;'"
    assert body["node_name"] == "node-1"
    assert body["egg_name"] == "Nginx"
    assert body["variables"] == {"SERVER_NAME": "My Server", "MOTD": "Hi"}
    assert [(a["port"], a["is_primary"]) for a in body["allocations"]] == [
        (25001, True),
        (25002, False),
    ]

    rows = client.get(f"/api/nodes/{env.node_id}/allocations").json()
    assert [r["server_name"] for r in rows] == ["Web 1", "Web 1", None]
    assert [s["id"] for s in client.get("/api/servers").json()] == [body["id"]]
    assert client.get(f"/api/servers/{body['id']}").json()["name"] == "Web 1"


def test_create_can_override_image_startup_and_limits(client, env):
    response = _post(
        client, env, image="nginx:1.26", startup="nginx", memory_mb=512, cpus=0.5, disk_mb=2048
    )
    body = response.json()
    assert (body["image"], body["startup"]) == ("nginx:1.26", "nginx")
    assert (body["memory_mb"], body["cpus"], body["disk_mb"]) == (512, 0.5, 2048)


def test_create_is_audited_without_variables(client, db_session, env):
    assert _post(client, env, variables={"MOTD": "secret"}).status_code == 201
    db_session.expire_all()
    entry = db_session.scalars(select(AuditLog).where(AuditLog.action == "server.create")).one()
    assert entry.details["name"] == "Web 1"
    assert "secret" not in str(entry.details)


def test_allocation_in_use_gives_409(client, env):
    assert _post(client, env).status_code == 201
    assert _post(client, env, name="Web 2").status_code == 409
    assert len(client.get("/api/servers").json()) == 1


def test_allocation_of_another_node_is_rejected(client, env):
    other = _create(client, env.headers, "node-2")
    foreign = make_allocations(client, env.headers, other, 25001)
    assert _post(client, env, allocation_id=foreign[0]).status_code == 422


def test_duplicate_allocation_in_one_request_is_rejected(client, env):
    response = _post(client, env, extra_allocation_ids=[env.allocations[0]])
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field", "expected"),
    [("owner_id", 404), ("node_id", 404), ("egg_id", 404), ("allocation_id", 422)],
)
def test_unknown_references_are_rejected(client, env, field, expected):
    assert _post(client, env, **{field: str(uuid.uuid4())}).status_code == expected
    assert client.get("/api/servers").json() == []


def test_unknown_variable_claims_nothing(client, env):
    assert _post(client, env, variables={"NOPE": "x"}).status_code == 422
    rows = client.get(f"/api/nodes/{env.node_id}/allocations").json()
    assert all(r["server_id"] is None for r in rows)


def test_update_server(client, env):
    server_id = _post(client, env).json()["id"]
    url = f"/api/servers/{server_id}"
    response = client.patch(
        url,
        json={"name": "Web 2", "memory_mb": 2048, "variables": {"MOTD": "New"}},
        headers=env.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["memory_mb"]) == ("Web 2", 2048)
    assert body["variables"] == {"SERVER_NAME": "My Server", "MOTD": "New"}
    unknown = client.patch(url, json={"variables": {"NOPE": "x"}}, headers=env.headers)
    assert unknown.status_code == 422
    assert client.patch(url, json={"name": None}, headers=env.headers).status_code == 422


def test_delete_frees_the_allocations(client, env):
    server_id = _post(client, env, extra_allocation_ids=[env.allocations[1]]).json()["id"]
    assert client.delete(f"/api/servers/{server_id}", headers=env.headers).status_code == 204
    assert client.get("/api/servers").json() == []
    rows = client.get(f"/api/nodes/{env.node_id}/allocations").json()
    assert all(r["server_id"] is None and not r["is_primary"] for r in rows)
    assert _post(client, env).status_code == 201


def test_running_server_cannot_be_deleted(client, db_session, env):
    server_id = _post(client, env).json()["id"]
    server = db_session.scalars(select(Server)).one()
    server.status = "running"
    db_session.commit()
    assert client.delete(f"/api/servers/{server_id}", headers=env.headers).status_code == 409


def test_things_in_use_cannot_be_deleted(client, env):
    server_id = _post(client, env).json()["id"]
    headers = env.headers
    allocation_url = f"/api/allocations/{env.allocations[0]}"
    assert client.delete(allocation_url, headers=headers).status_code == 409
    assert client.delete(f"/api/eggs/{env.egg_id}", headers=headers).status_code == 409
    assert client.delete(f"/api/nodes/{env.node_id}", headers=headers).status_code == 409
    assert client.delete(f"/api/servers/{server_id}", headers=headers).status_code == 204
    assert client.delete(f"/api/nodes/{env.node_id}", headers=headers).status_code == 204


def test_unknown_server_gives_404(client, env):
    assert client.get(f"/api/servers/{uuid.uuid4()}").status_code == 404
    assert client.delete(f"/api/servers/{uuid.uuid4()}", headers=env.headers).status_code == 404


def test_csrf_token_is_required(client, env):
    body = {
        "name": "Web 1",
        "owner_id": str(env.user.id),
        "node_id": env.node_id,
        "egg_id": env.egg_id,
        "allocation_id": env.allocations[0],
    }
    assert client.post("/api/servers", json=body).status_code == 403
    assert client.get("/api/servers").json() == []


@pytest.mark.parametrize(
    "changes",
    [
        {"memory_mb": 1},
        {"cpus": 0.05},
        {"disk_mb": 1},
        {"name": ""},
        {"image": "-rm"},
        {"privileged": True},
        {"variables": {"lower": "x"}},
        {"variables": {"MOTD": "a\nb"}},
    ],
)
def test_invalid_input_is_rejected(client, env, changes):
    assert _post(client, env, **changes).status_code == 422
    assert client.get("/api/servers").json() == []
