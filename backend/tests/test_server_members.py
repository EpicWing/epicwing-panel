import uuid

from sqlalchemy import select

from app.models import AuditLog, User
from tests import test_server_access as _access
from tests.conftest import TEST_PASSWORD
from tests.test_nodes_detail import _login
from tests.test_server_access import P, _grant

world = _access.world


def _url(world):
    return f"/api/servers/{world.server_id}/access"


def _account(db_session, email):
    return db_session.scalar(select(User).where(User.email == email))


def _as(client, account):
    response = client.post(
        "/api/auth/login", json={"email": account.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_admin_adds_lists_updates_removes(client, user, db_session, world):
    headers = _login(client, user)
    added = client.post(
        _url(world),
        json={"email": "stranger@example.test", "permissions": ["files.read", "console.view"]},
        headers=headers,
    )
    assert added.status_code == 201, added.text
    assert added.json()["permissions"] == ["console.view", "files.read"]
    member_id = added.json()["id"]

    listing = client.get(_url(world)).json()
    assert "stranger@example.test" in [m["email"] for m in listing["members"]]
    assert "server.view" not in listing["available_permissions"]

    updated = client.put(
        f"{_url(world)}/{member_id}", json={"permissions": ["files.read"]}, headers=headers
    )
    assert updated.status_code == 200 and updated.json()["permissions"] == ["files.read"]

    assert client.delete(f"{_url(world)}/{member_id}", headers=headers).status_code == 204
    members = client.get(_url(world)).json()["members"]
    assert "stranger@example.test" not in [m["email"] for m in members]

    actions = set(db_session.scalars(select(AuditLog.action)))
    assert {"server.access.add", "server.access.update", "server.access.remove"} <= actions


def test_unknown_permission_is_rejected(client, user, world):
    headers = _login(client, user)
    response = client.post(
        _url(world),
        json={"email": "stranger@example.test", "permissions": ["root.everything"]},
        headers=headers,
    )
    assert response.status_code == 422


def test_owner_and_duplicates_are_conflicts(client, user, world):
    headers = _login(client, user)
    owner = client.post(
        _url(world), json={"email": "owner@example.test", "permissions": []}, headers=headers
    )
    assert owner.status_code == 409
    body = {"email": "stranger@example.test", "permissions": []}
    assert client.post(_url(world), json=body, headers=headers).status_code == 201
    assert client.post(_url(world), json=body, headers=headers).status_code == 409
    missing = {"email": "nobody@example.test", "permissions": []}
    # Gleiche Antwort wie bei einem existierenden Mitglied, damit E-Mail-Adressen
    # nicht über den Statuscode enumeriert werden können.
    assert client.post(_url(world), json=missing, headers=headers).status_code == 409


def test_viewing_needs_access_view(client, db_session, world):
    _grant(db_session, world, _account(db_session, "member@example.test"), P.FILES_READ)
    _as(client, _account(db_session, "member@example.test"))
    assert client.get(_url(world)).status_code == 403
    _as(client, _account(db_session, "stranger@example.test"))
    assert client.get(_url(world)).status_code == 404


def test_owner_manages_without_being_admin(client, db_session, world):
    headers = _as(client, _account(db_session, "owner@example.test"))
    response = client.post(
        _url(world),
        json={"email": "stranger@example.test", "permissions": ["files.write"]},
        headers=headers,
    )
    assert response.status_code == 201, response.text


def test_manager_cannot_grant_what_they_lack(client, db_session, world):
    member = _account(db_session, "member@example.test")
    _grant(db_session, world, member, P.ACCESS_VIEW, P.ACCESS_MANAGE, P.FILES_READ)
    headers = _as(client, member)
    body = {"email": "stranger@example.test", "permissions": ["files.write"]}
    assert client.post(_url(world), json=body, headers=headers).status_code == 403
    body["permissions"] = ["files.read"]
    assert client.post(_url(world), json=body, headers=headers).status_code == 201


def test_manager_cannot_change_own_access(client, db_session, world):
    member = _account(db_session, "member@example.test")
    row = _grant(db_session, world, member, P.ACCESS_VIEW, P.ACCESS_MANAGE)
    headers = _as(client, member)
    own = f"{_url(world)}/{row.id}"
    response = client.put(own, json={"permissions": ["access.manage"]}, headers=headers)
    assert response.status_code == 403
    assert client.delete(own, headers=headers).status_code == 204


def test_manager_cannot_touch_stronger_member(client, user, db_session, world):
    admin_headers = _login(client, user)
    strong = client.post(
        _url(world),
        json={"email": "stranger@example.test", "permissions": ["files.read", "files.write"]},
        headers=admin_headers,
    ).json()["id"]
    member = _account(db_session, "member@example.test")
    _grant(db_session, world, member, P.ACCESS_VIEW, P.ACCESS_MANAGE, P.FILES_READ)
    headers = _as(client, member)
    target = f"{_url(world)}/{strong}"
    assert client.put(target, json={"permissions": []}, headers=headers).status_code == 403
    assert client.delete(target, headers=headers).status_code == 403


def test_unknown_member_is_404(client, user, world):
    headers = _login(client, user)
    response = client.put(
        f"{_url(world)}/{uuid.uuid4()}", json={"permissions": []}, headers=headers
    )
    assert response.status_code == 404
