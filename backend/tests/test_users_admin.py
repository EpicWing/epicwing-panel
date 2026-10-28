import uuid

from sqlalchemy import func, select

from app.models import AuditLog, Role, RolePermission, User, UserRole, UserSession
from app.security.passwords import hash_password
from app.security.permissions import Permission
from app.security.sessions import create_session
from tests import test_server_access as _access
from tests.conftest import TEST_PASSWORD
from tests.test_nodes_detail import _login

world = _access.world
NEW_PASSWORD = "a-long-new-password"


def _plain(db_session, email):
    account = User(email=email, password_hash=hash_password(TEST_PASSWORD), is_admin=False)
    db_session.add(account)
    db_session.commit()
    return account


def _manager(db_session, email="manager@example.test"):
    account = _plain(db_session, email)
    role = Role(name=f"user-manager-{uuid.uuid4()}", scope="global")
    db_session.add(role)
    db_session.flush()
    db_session.add(RolePermission(role_id=role.id, permission=Permission.USERS_MANAGE.value))
    db_session.add(UserRole(user_id=account.id, role_id=role.id))
    db_session.commit()
    return account


def _login_as(client, email, password=TEST_PASSWORD):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    return response, {"X-CSRF-Token": response.json().get("csrf_token", "")}


def _create(client, headers, email="new@example.test", **extra):
    body = {"email": email, "password": TEST_PASSWORD, **extra}
    return client.post("/api/users", json=body, headers=headers)


def test_admin_lifecycle(client, user, db_session):
    headers = _login(client, user)
    created = _create(client, headers, email="  New@Example.test ")
    assert created.status_code == 201, created.text
    new_id = created.json()["id"]
    assert created.json()["email"] == "new@example.test"
    assert created.json()["is_admin"] is False

    listing = client.get("/api/users", params={"q": "NEW@"}).json()
    assert [u["email"] for u in listing] == ["new@example.test"]
    assert client.get("/api/users", params={"q": "100%"}).json() == []

    changed = client.patch(
        f"/api/users/{new_id}", json={"email": "renamed@example.test"}, headers=headers
    )
    assert changed.status_code == 200 and changed.json()["email"] == "renamed@example.test"

    disabled = client.post(f"/api/users/{new_id}/disable", headers=headers)
    assert disabled.status_code == 200 and disabled.json()["disabled_at"] is not None
    enabled = client.post(f"/api/users/{new_id}/enable", headers=headers)
    assert enabled.json()["disabled_at"] is None

    assert client.delete(f"/api/users/{new_id}", headers=headers).status_code == 204
    assert client.get(f"/api/users/{new_id}").status_code == 404
    actions = set(db_session.scalars(select(AuditLog.action)))
    assert {"user.create", "user.update", "user.disable", "user.enable", "user.delete"} <= actions


def test_validation_and_duplicates(client, user):
    headers = _login(client, user)
    assert _create(client, headers, email="not-an-email").status_code == 422
    short = {"email": "a@example.test", "password": "short"}
    assert client.post("/api/users", json=short, headers=headers).status_code == 422
    assert _create(client, headers, email="dup@example.test").status_code == 201
    assert _create(client, headers, email="DUP@example.test").status_code == 409


def test_disabled_user_cannot_log_in_and_loses_sessions(client, user, db_session):
    headers = _login(client, user)
    target = _plain(db_session, "target@example.test")
    create_session(db_session, target, "127.0.0.1", "pytest")
    db_session.commit()
    count = select(func.count()).select_from(UserSession).where(UserSession.user_id == target.id)
    assert db_session.scalar(count) == 1

    assert client.post(f"/api/users/{target.id}/disable", headers=headers).status_code == 200
    db_session.expire_all()
    assert db_session.scalar(count) == 0
    assert _login_as(client, "target@example.test")[0].status_code == 401


def test_password_reset(client, user, db_session):
    headers = _login(client, user)
    target = _plain(db_session, "target@example.test")
    url = f"/api/users/{target.id}/password"
    assert client.post(url, json={"new_password": "short"}, headers=headers).status_code == 422
    assert client.post(url, json={"new_password": NEW_PASSWORD}, headers=headers).status_code == 204
    entry = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "user.password_reset")
    ).one()
    assert NEW_PASSWORD not in str(entry.details) and "target@" not in str(entry.details)

    assert _login_as(client, "target@example.test")[0].status_code == 401
    assert _login_as(client, "target@example.test", NEW_PASSWORD)[0].status_code == 200


def test_manager_limits(client, user, db_session):
    _login(client, user)
    admin_target = str(user.id)
    _manager(db_session)
    _plain(db_session, "regular@example.test")
    _, headers = _login_as(client, "manager@example.test")

    assert _create(client, headers, email="x@example.test", is_admin=True).status_code == 403
    assert _create(client, headers, email="y@example.test").status_code == 201
    assert client.post(f"/api/users/{admin_target}/disable", headers=headers).status_code == 403
    assert client.delete(f"/api/users/{admin_target}", headers=headers).status_code == 403
    patch = client.patch(f"/api/users/{admin_target}", json={"email": "a@b.test"}, headers=headers)
    assert patch.status_code == 403

    regular = db_session.scalar(select(User.id).where(User.email == "regular@example.test"))
    promote = client.patch(f"/api/users/{regular}", json={"is_admin": True}, headers=headers)
    assert promote.status_code == 403
    reset = client.post(
        f"/api/users/{regular}/password", json={"new_password": NEW_PASSWORD}, headers=headers
    )
    assert reset.status_code == 403
    assert client.post(f"/api/users/{regular}/disable", headers=headers).status_code == 200


def test_no_self_harm(client, user):
    headers = _login(client, user)
    me = f"/api/users/{user.id}"
    assert client.post(f"{me}/disable", headers=headers).status_code == 409
    assert client.delete(me, headers=headers).status_code == 409
    assert client.patch(me, json={"is_admin": False}, headers=headers).status_code == 409
    own = client.post(f"{me}/password", json={"new_password": NEW_PASSWORD}, headers=headers)
    assert own.status_code == 409


def test_owner_of_servers_is_not_deleted(client, user, db_session, world):
    headers = _login(client, user)
    owner = db_session.scalar(select(User.id).where(User.email == "owner@example.test"))
    response = client.delete(f"/api/users/{owner}", headers=headers)
    assert response.status_code == 409
    assert "owns servers" in response.json()["detail"]
    assert client.get(f"/api/users/{owner}").json()["server_count"] == 1


def test_needs_users_manage(client, user, db_session):
    _plain(db_session, "plain@example.test")
    _, headers = _login_as(client, "plain@example.test")
    assert client.get("/api/users").status_code == 403
    assert _create(client, headers).status_code == 403
