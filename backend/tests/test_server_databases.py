import uuid

import pytest

from app.api.server_databases import PER_SERVER_LIMIT
from app.services import dbhost
from tests import test_server_power as base

server = base.server
broker = base.broker

HOSTS = "/api/admin/database-hosts"


class FakeMariaDB:
    def __init__(self):
        self.created = []
        self.passwords = []
        self.dropped = []
        self.fail = False

    def _check(self):
        if self.fail:
            raise dbhost.HostError("Could not connect to the database host.")

    def ping(self, endpoint):
        self._check()
        return "10.11.0-fake"

    def create_database(self, endpoint, name, user, remote, password):
        self._check()
        self.created.append((name, user, remote, password))

    def set_password(self, endpoint, user, remote, password):
        self._check()
        self.passwords.append((user, remote, password))

    def drop_database(self, endpoint, name, user, remote):
        self._check()
        self.dropped.append((name, user, remote))


@pytest.fixture
def mariadb(monkeypatch):
    fake = FakeMariaDB()
    for name in ("ping", "create_database", "set_password", "drop_database"):
        monkeypatch.setattr(dbhost, name, getattr(fake, name))
    return fake


def _add_host(client, server, **changes):
    body = {
        "name": "Local",
        "host": "172.17.0.1",
        "port": 3306,
        "admin_user": "epicwing",
        "admin_password": "secret-pass",
    }
    body.update(changes)
    return client.post(HOSTS, json=body, headers=server.headers)


@pytest.fixture
def host(client, server, mariadb):
    response = _add_host(client, server)
    assert response.status_code == 201, response.text
    return response.json()


def _url(server):
    return server.url + "/databases"


def _create(client, server, name="main", **body):
    return client.post(_url(server), json={"name": name, **body}, headers=server.headers)


def test_host_password_is_never_returned(client, server, mariadb):
    response = _add_host(client, server)
    assert response.status_code == 201, response.text
    assert "secret-pass" not in response.text
    assert "admin_password" not in response.json()
    listing = client.get(HOSTS, headers=server.headers)
    assert "secret-pass" not in listing.text
    assert listing.json()[0]["database_count"] == 0


def test_host_needs_working_connection(client, server, mariadb):
    mariadb.fail = True
    assert _add_host(client, server).status_code == 400
    assert client.get(HOSTS, headers=server.headers).json() == []


def test_host_name_must_be_unique(client, server, host):
    assert _add_host(client, server).status_code == 409


def test_host_test_endpoint(client, server, host, mariadb):
    url = f"{HOSTS}/{host['id']}/test"
    assert client.post(url, headers=server.headers).json() == {
        "ok": True,
        "message": "10.11.0-fake",
    }
    mariadb.fail = True
    assert client.post(url, headers=server.headers).json()["ok"] is False


def test_create_without_host_is_conflict(client, server, mariadb):
    assert _create(client, server).status_code == 409


def test_create_and_list(client, server, host, mariadb):
    response = _create(client, server)
    assert response.status_code == 201, response.text
    body = response.json()
    prefix = f"s{uuid.UUID(server.id).hex[:8]}_"
    assert body["name"] == prefix + "main"
    assert body["username"].startswith("u")
    assert body["remote"] == "%"
    assert len(body["password"]) == 24
    assert mariadb.created == [(body["name"], body["username"], "%", body["password"])]
    items = client.get(_url(server), headers=server.headers).json()
    assert items["limit"] == PER_SERVER_LIMIT
    assert [item["id"] for item in items["items"]] == [body["id"]]
    assert items["items"][0]["password"] == body["password"]


def test_name_and_remote_are_validated(client, server, host):
    assert _create(client, server, name="bad name!").status_code == 422
    assert _create(client, server, name="").status_code == 422
    assert _create(client, server, remote="x'; DROP").status_code == 422
    ok = _create(client, server, name="net", remote="10.0.%")
    assert ok.status_code == 201
    assert ok.json()["remote"] == "10.0.%"


def test_duplicate_name_is_conflict(client, server, host):
    assert _create(client, server).status_code == 201
    assert _create(client, server).status_code == 409


def test_server_limit(client, server, host):
    for index in range(PER_SERVER_LIMIT):
        assert _create(client, server, name=f"db{index}").status_code == 201
    assert _create(client, server, name="one_too_many").status_code == 409


def test_host_capacity_is_respected(client, server, mariadb):
    assert _add_host(client, server, max_databases=1).status_code == 201
    assert _create(client, server, name="first").status_code == 201
    second = _create(client, server, name="second")
    assert second.status_code == 409
    assert "No database host" in second.json()["detail"]


def test_host_failure_leaves_nothing_behind(client, server, host, mariadb):
    mariadb.fail = True
    assert _create(client, server).status_code == 502
    mariadb.fail = False
    assert client.get(_url(server), headers=server.headers).json()["items"] == []


def test_rotate_password(client, server, host, mariadb):
    created = _create(client, server).json()
    response = client.post(f"{_url(server)}/{created['id']}/rotate", headers=server.headers)
    assert response.status_code == 200, response.text
    assert response.json()["password"] != created["password"]
    assert mariadb.passwords == [(created["username"], "%", response.json()["password"])]


def test_delete_database(client, server, host, mariadb):
    created = _create(client, server).json()
    response = client.delete(f"{_url(server)}/{created['id']}", headers=server.headers)
    assert response.status_code == 204
    assert mariadb.dropped == [(created["name"], created["username"], "%")]
    assert client.get(_url(server), headers=server.headers).json()["items"] == []


def test_unknown_database_is_404(client, server, host):
    url = f"{_url(server)}/{uuid.uuid4()}"
    assert client.delete(url, headers=server.headers).status_code == 404
    assert client.post(url + "/rotate", headers=server.headers).status_code == 404


def test_host_in_use_cannot_be_deleted(client, server, host):
    created = _create(client, server).json()
    url = f"{HOSTS}/{host['id']}"
    assert client.delete(url, headers=server.headers).status_code == 409
    client.delete(f"{_url(server)}/{created['id']}", headers=server.headers)
    assert client.delete(url, headers=server.headers).status_code == 204


def test_deleting_a_server_drops_its_databases(client, server, host, mariadb):
    created = _create(client, server).json()
    response = client.delete(server.url, headers=server.headers)
    assert response.status_code == 204, response.text
    assert mariadb.dropped == [(created["name"], created["username"], "%")]


def test_server_stays_when_host_is_down(client, server, host, mariadb):
    _create(client, server)
    mariadb.fail = True
    assert client.delete(server.url, headers=server.headers).status_code == 502
    assert client.get(server.url, headers=server.headers).status_code == 200
    mariadb.fail = False
    assert client.delete(server.url, headers=server.headers).status_code == 204
