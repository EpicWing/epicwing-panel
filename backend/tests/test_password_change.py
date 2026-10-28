from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AuditLog

PASSWORD = "correct-horse-battery"  # noqa: S105
NEW_PASSWORD = "a-much-longer-new-password"  # noqa: S105


def _login(client, email, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _csrf(client, email):
    response = _login(client, email)
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _change(client, headers, current=PASSWORD, new=NEW_PASSWORD):
    return client.post(
        "/api/auth/password",
        json={"current_password": current, "new_password": new},
        headers=headers,
    )


def test_requires_login(client):
    response = client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 401


def test_requires_csrf_token(client, user):
    _csrf(client, user.email)
    response = client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 403


def test_new_password_works_and_old_one_does_not(client, user):
    headers = _csrf(client, user.email)
    assert _change(client, headers).status_code == 204
    assert _login(client, user.email, NEW_PASSWORD).status_code == 200
    assert _login(client, user.email, PASSWORD).status_code == 401


def test_wrong_current_password_changes_nothing(client, user):
    headers = _csrf(client, user.email)
    assert _change(client, headers, current="not-the-password").status_code == 400
    assert _login(client, user.email, PASSWORD).status_code == 200


def test_too_short_password_is_rejected(client, user):
    headers = _csrf(client, user.email)
    assert _change(client, headers, new="short").status_code == 422


def test_same_password_is_rejected(client, user):
    headers = _csrf(client, user.email)
    assert _change(client, headers, new=PASSWORD).status_code == 400


def test_other_sessions_are_ended_but_not_the_current_one(client, user):
    other = TestClient(app)
    _csrf(other, user.email)
    headers = _csrf(client, user.email)
    assert other.get("/api/auth/me").status_code == 200

    assert _change(client, headers).status_code == 204
    assert other.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200


def test_repeated_wrong_attempts_are_limited(client, user):
    headers = _csrf(client, user.email)
    for _ in range(5):
        assert _change(client, headers, current="not-the-password").status_code == 400
    assert _change(client, headers).status_code == 429


def test_change_is_audited_without_password(client, db_session, user):
    headers = _csrf(client, user.email)
    assert _change(client, headers).status_code == 204
    entry = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "auth.password_change")
    ).one()
    assert entry.actor_id == user.id
    assert NEW_PASSWORD not in str(entry.details)
