import uuid

import pytest

from tests.factories import make_allocations
from tests.test_nodes_detail import _create, _login


def _url(node_id):
    return f"/api/nodes/{node_id}/allocations"


def test_create_single_port_and_range(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers)
    one = client.post(
        _url(node_id), json={"ip": "203.0.113.45", "port_start": 25565}, headers=headers
    )
    assert one.status_code == 201
    assert [row["port"] for row in one.json()] == [25565]

    assert len(make_allocations(client, headers, node_id, 25010, 25014)) == 5
    rows = client.get(_url(node_id)).json()
    assert [r["port"] for r in rows] == [25010, 25011, 25012, 25013, 25014, 25565]
    assert all(r["server_id"] is None and not r["is_primary"] for r in rows)


def test_ports_from_1024_are_allowed(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers, port_range_start=1024, port_range_end=65535)
    for port in (1024, 7777, 27015, 65535):
        body = {"ip": "203.0.113.45", "port_start": port}
        assert client.post(_url(node_id), json=body, headers=headers).status_code == 201
    assert [r["port"] for r in client.get(_url(node_id)).json()] == [1024, 7777, 27015, 65535]


def test_any_port_from_1024_to_65535_is_allowed(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers)
    for port in (1024, 24999, 26000, 65535):
        body = {"ip": "203.0.113.45", "port_start": port}
        assert client.post(_url(node_id), json=body, headers=headers).status_code == 201


def test_ports_outside_1024_to_65535_are_rejected(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers)
    for body in (
        {"ip": "203.0.113.45", "port_start": 0},
        {"ip": "203.0.113.45", "port_start": 1023},
        {"ip": "203.0.113.45", "port_start": 65536},
        {"ip": "203.0.113.45", "port_start": 65530, "port_end": 65536},
    ):
        assert client.post(_url(node_id), json=body, headers=headers).status_code == 422
    assert client.get(_url(node_id)).json() == []


def test_duplicate_creates_nothing(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers)
    make_allocations(client, headers, node_id, 25001, 25003)
    response = client.post(
        _url(node_id),
        json={"ip": "203.0.113.45", "port_start": 25003, "port_end": 25005},
        headers=headers,
    )
    assert response.status_code == 409
    assert [r["port"] for r in client.get(_url(node_id)).json()] == [25001, 25002, 25003]


def test_same_port_on_another_ip_is_allowed(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers)
    make_allocations(client, headers, node_id, 25001, ip="203.0.113.45")
    make_allocations(client, headers, node_id, 25001, ip="10.0.0.5")
    assert len(client.get(_url(node_id)).json()) == 2


def test_delete_free_allocation(client, user):
    headers = _login(client, user)
    node_id = _create(client, headers)
    [allocation_id] = make_allocations(client, headers, node_id)
    assert client.delete(f"/api/allocations/{allocation_id}", headers=headers).status_code == 204
    assert client.get(_url(node_id)).json() == []
    assert client.delete(f"/api/allocations/{allocation_id}", headers=headers).status_code == 404


def test_unknown_node_gives_404(client, user):
    headers = _login(client, user)
    assert client.get(_url(uuid.uuid4())).status_code == 404
    body = {"ip": "203.0.113.45", "port_start": 25001}
    assert client.post(_url(uuid.uuid4()), json=body, headers=headers).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"ip": "not-an-ip", "port_start": 25001},
        {"ip": "203.0.113.45", "port_start": 0},
        {"ip": "203.0.113.45", "port_start": 65536},
        {"ip": "203.0.113.45", "port_start": 65535, "port_end": 65536},
        {"ip": "203.0.113.45", "port_start": 1023},
        {"ip": "203.0.113.45", "port_start": 1023},
        {"ip": "203.0.113.45", "port_start": 25010, "port_end": 25001},
        {"ip": "203.0.113.45", "port_start": 25000, "port_end": 25600},
        {"ip": "203.0.113.45", "port_start": 25001, "protocol": "tcp"},
    ],
)
def test_invalid_input_is_rejected(client, user, body):
    headers = _login(client, user)
    node_id = _create(client, headers)
    assert client.post(_url(node_id), json=body, headers=headers).status_code == 422
