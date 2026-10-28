import pytest
from sqlalchemy import select

from app.main import app
from app.models import AuditLog, Role, RolePermission, User, UserRole
from app.security.passwords import hash_password
from app.security.permissions import Permission
from app.security.apikeys import get_server_auth
from app.security.sessions import get_auth
from tests.helpers import collect_routes

PASSWORD = "correct-horse-battery"
ADMIN_EMAIL = "admin@example.test"
USER_EMAIL = "user@example.test"

# Routen, die ohne Anmeldung erreichbar sein dürfen.
PUBLIC_ROUTES = {
    ("/api/panel", "GET"),
    ("/api/health", "GET"),
    ("/api/auth/login", "POST"),
    ("/api/auth/login/2fa", "POST"),
    # Der Agent hat noch kein Konto und weist sich mit einem einmaligen Token aus.
    ("/api/agent/enroll", "POST"),
}


@pytest.fixture
def plain_user(db_session):
    account = User(email=USER_EMAIL, password_hash=hash_password(PASSWORD), is_admin=False)
    db_session.add(account)
    db_session.commit()
    return account


def _login(client, email):
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200


def _grant(db, account, permission):
    role = Role(name="tester", scope="global")
    db.add(role)
    db.flush()
    db.add(RolePermission(role_id=role.id, permission=permission.value))
    db.add(UserRole(user_id=account.id, role_id=role.id))
    db.commit()


def _depends_on(dependant, target):
    return any(d.call is target or _depends_on(d, target) for d in dependant.dependencies)


def test_every_route_requires_auth():
    routes = [r for r in collect_routes(app) if not r.websocket]
    # Schutz gegen Leerlauf: Der Test muss die Routen wirklich sehen.
    assert len(routes) >= 11, f"Nur {len(routes)} HTTP-Routen gefunden"
    found = {(r.path, m) for r in routes for m in r.methods}
    assert PUBLIC_ROUTES <= found, f"Öffentliche Routen nicht gefunden: {PUBLIC_ROUTES - found}"

    unprotected = []
    for route in routes:
        for method in sorted(route.methods):
            if (route.path, method) in PUBLIC_ROUTES:
                continue
            if not (
                _depends_on(route.dependant, get_auth)
                or _depends_on(route.dependant, get_server_auth)
            ):
                unprotected.append(f"{method} {route.path}")
    assert not unprotected, f"Routen ohne Auth-Prüfung: {unprotected}"


def test_users_requires_login(client):
    assert client.get("/api/users").status_code == 401


def test_users_forbidden_without_permission(client, user, plain_user):
    _login(client, USER_EMAIL)
    assert client.get("/api/users").status_code == 403


def test_users_allowed_for_admin(client, user, plain_user):
    _login(client, ADMIN_EMAIL)
    response = client.get("/api/users")
    assert response.status_code == 200
    assert {u["email"] for u in response.json()} == {ADMIN_EMAIL, USER_EMAIL}


def test_users_allowed_with_role(client, db_session, user, plain_user):
    _grant(db_session, plain_user, Permission.USERS_MANAGE)
    _login(client, USER_EMAIL)
    assert client.get("/api/users").status_code == 200
    # Das Recht gilt nur für das, was die Rolle erlaubt.
    assert client.get("/api/audit-logs").status_code == 403


def test_audit_log_forbidden_without_permission(client, user, plain_user):
    _login(client, USER_EMAIL)
    assert client.get("/api/audit-logs").status_code == 403


def test_login_is_audited(client, db_session, user):
    _login(client, ADMIN_EMAIL)
    entries = db_session.scalars(select(AuditLog)).all()
    assert [e.action for e in entries] == ["auth.login"]
    assert entries[0].actor_id == user.id


def test_failed_login_is_audited_without_email(client, db_session, user):
    response = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": "falsch-falsch-falsch"}
    )
    assert response.status_code == 401
    entry = db_session.scalars(select(AuditLog)).one()
    assert entry.action == "auth.login_failed"
    assert entry.details == {"reason": "invalid_credentials"}
    assert "example.test" not in str(entry.details)


def test_audit_log_endpoint_lists_entries(client, user):
    _login(client, ADMIN_EMAIL)
    response = client.get("/api/audit-logs")
    assert response.status_code == 200
    assert response.json()[0]["action"] == "auth.login"
