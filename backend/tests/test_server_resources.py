import pytest

from tests.factories import make_allocations, make_egg, make_nest
from tests.test_nodes_detail import _create, _login


def _setup(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers)
    egg_id = make_egg(client, headers, make_nest(client, headers))
    allocations = make_allocations(client, headers, node_id, 25001, 25002)
    return headers, node_id, egg_id, allocations


def _post(client, user, ctx, **changes):
    headers, node_id, egg_id, allocations = ctx
    body = {
        "name": "Game 1",
        "owner_id": str(user.id),
        "node_id": node_id,
        "egg_id": egg_id,
        "allocation_id": allocations[0],
    }
    body.update(changes)
    return client.post("/api/servers", json=body, headers=headers)


def test_zero_means_unlimited(client, user):
    ctx = _setup(client, user)
    response = _post(client, user, ctx, memory_mb=0, cpus=0, disk_mb=0)
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["memory_mb"], body["cpus"], body["disk_mb"]) == (0, 0, 0)


@pytest.mark.parametrize(
    "changes",
    [
        {"memory_mb": 8},
        {"memory_mb": -1},
        {"cpus": 0.05},
        {"cpus": -1},
        {"disk_mb": 50},
        {"disk_mb": -1},
    ],
)
def test_values_between_zero_and_the_minimum_are_rejected(client, user, changes):
    ctx = _setup(client, user)
    assert _post(client, user, ctx, **changes).status_code == 422
    assert client.get("/api/servers").json() == []


def test_update_to_unlimited_and_back(client, user):
    ctx = _setup(client, user)
    server_id = _post(client, user, ctx).json()["id"]
    url = f"/api/servers/{server_id}"
    headers = ctx[0]
    response = client.patch(url, json={"memory_mb": 0, "cpus": 0}, headers=headers)
    assert response.status_code == 200
    assert (response.json()["memory_mb"], response.json()["cpus"]) == (0, 0)
    assert client.patch(url, json={"memory_mb": 5}, headers=headers).status_code == 422
    assert client.patch(url, json={"memory_mb": 512}, headers=headers).status_code == 200
