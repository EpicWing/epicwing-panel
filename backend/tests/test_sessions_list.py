from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import AuditLog, User
from app.security.passwords import hash_password
from app.security.sessions import create_session


def _login(client, credentials):
    response = client.post("/api/auth/login", json=credentials)
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _device(db_session, user, agent="Firefox"):
    _token, session = create_session(db_session, user, "203.0.113.5", agent)
    return session


def test_sessions_need_login(client):
    assert client.get("/api/auth/sessions").status_code == 401


def test_list_marks_current_and_hides_ended(client, db_session, user, credentials):
    _login(client, credentials)
    other = _device(db_session, user)
    revoked = _device(db_session, user)
    revoked.revoked_at = datetime.now(UTC)
    idle = _device(db_session, user)
    idle.last_seen_at = datetime.now(UTC) - timedelta(days=2)
    db_session.commit()

    rows = client.get("/api/auth/sessions").json()
    current = {r["id"]: r["current"] for r in rows}
    assert current[str(other.id)] is False
    assert str(revoked.id) not in current
    assert str(idle.id) not in current
    assert sum(current.values()) == 1


def test_end_other_session(client, db_session, user, credentials):
    headers = _login(client, credentials)
    other = _device(db_session, user)
    response = client.delete(f"/api/auth/sessions/{other.id}", headers=headers)
    assert response.status_code == 204
    db_session.refresh(other)
    assert other.revoked_at is not None
    assert client.get("/api/auth/me").status_code == 200
    entry = db_session.scalar(select(AuditLog).where(AuditLog.action == "session.revoke"))
    assert entry is not None


def test_cannot_end_current_session(client, credentials):
    headers = _login(client, credentials)
    rows = client.get("/api/auth/sessions").json()
    current = next(r for r in rows if r["current"])
    response = client.delete(f"/api/auth/sessions/{current['id']}", headers=headers)
    assert response.status_code == 409
    assert client.get("/api/auth/me").status_code == 200


def test_end_needs_csrf_token(client, db_session, user, credentials):
    _login(client, credentials)
    other = _device(db_session, user)
    assert client.delete(f"/api/auth/sessions/{other.id}").status_code == 403


def test_foreign_session_is_hidden_and_untouchable(client, db_session, credentials):
    headers = _login(client, credentials)
    stranger = User(
        email="stranger@example.test",
        password_hash=hash_password("some-long-password"),
        is_admin=False,
    )
    db_session.add(stranger)
    db_session.commit()
    foreign = _device(db_session, stranger)

    ids = {r["id"] for r in client.get("/api/auth/sessions").json()}
    assert str(foreign.id) not in ids
    response = client.delete(f"/api/auth/sessions/{foreign.id}", headers=headers)
    assert response.status_code == 404
    db_session.refresh(foreign)
    assert foreign.revoked_at is None
