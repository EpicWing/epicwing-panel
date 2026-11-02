from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.api_keys import MAX_KEYS
from app.db import get_db
from app.models import ApiKey, User
from app.security.apikeys import KEY_PREFIX, ServerAuth
from app.security.sessions import hash_token


def _login(client, credentials) -> dict[str, str]:
    reply = client.post("/api/auth/login", json=credentials)
    assert reply.status_code == 200, reply.text
    return {"X-CSRF-Token": reply.json()["csrf_token"]}


def _create(client, headers, **body) -> dict:
    body.setdefault("name", "ci")
    reply = client.post("/api/api-keys", json=body, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _probe(db_session) -> TestClient:
    """Mini app with ServerAuth, so login can be tested without real server routes."""
    probe = FastAPI()

    @probe.get("/probe")
    def read(auth: ServerAuth) -> dict[str, str]:
        return {"user": auth.user.email}

    @probe.post("/probe")
    def write(auth: ServerAuth) -> dict[str, str]:
        return {"user": auth.user.email}

    probe.dependency_overrides[get_db] = lambda: db_session
    return TestClient(probe)


def test_token_is_shown_once_and_only_the_hash_is_stored(client, credentials, db_session):
    headers = _login(client, credentials)
    created = _create(client, headers, name="deploy")
    token = created["token"]
    assert token.startswith(KEY_PREFIX)
    assert created["prefix"] == token[:12]

    listed = client.get("/api/api-keys").json()
    assert [row["name"] for row in listed] == ["deploy"]
    assert "token" not in listed[0]

    row = db_session.scalar(select(ApiKey))
    assert row.token_hash == hash_token(token)
    assert row.token_hash != token


def test_creating_a_key_needs_a_session(client):
    assert client.post("/api/api-keys", json={"name": "x"}).status_code == 401


def test_blank_name_is_rejected(client, credentials):
    headers = _login(client, credentials)
    reply = client.post("/api/api-keys", json={"name": "   "}, headers=headers)
    assert reply.status_code == 422


def test_keys_are_limited_per_user(client, credentials, db_session, user):
    for i in range(MAX_KEYS):
        db_session.add(
            ApiKey(
                user_id=user.id,
                name=f"k{i}",
                prefix="ewk_xxxxxxxx",
                token_hash=hash_token(f"t{i}"),
            )
        )
    db_session.commit()
    headers = _login(client, credentials)
    reply = client.post("/api/api-keys", json={"name": "one more"}, headers=headers)
    assert reply.status_code == 409


def test_other_users_keys_are_invisible(client, credentials, db_session):
    other = User(email="other@example.test", password_hash="not-a-real-hash")
    db_session.add(other)
    db_session.commit()
    foreign = ApiKey(
        user_id=other.id, name="theirs", prefix="ewk_xxxxxxxx", token_hash=hash_token("foreign")
    )
    db_session.add(foreign)
    db_session.commit()

    headers = _login(client, credentials)
    assert client.get("/api/api-keys").json() == []
    assert client.delete(f"/api/api-keys/{foreign.id}", headers=headers).status_code == 404
    assert db_session.get(ApiKey, foreign.id) is not None


def test_a_key_works_where_server_auth_is_used(client, credentials, db_session):
    headers = _login(client, credentials)
    token = _create(client, headers)["token"]
    reply = _probe(db_session).get("/probe", headers=_bearer(token))
    assert reply.status_code == 200
    assert reply.json() == {"user": "admin@example.test"}
    assert db_session.scalar(select(ApiKey)).last_used_at is not None


def test_a_key_needs_no_csrf_token(client, credentials, db_session):
    headers = _login(client, credentials)
    token = _create(client, headers)["token"]
    assert _probe(db_session).post("/probe", headers=_bearer(token)).status_code == 200


def test_read_only_key_cannot_write(client, credentials, db_session):
    headers = _login(client, credentials)
    token = _create(client, headers, read_only=True)["token"]
    probe = _probe(db_session)
    assert probe.get("/probe", headers=_bearer(token)).status_code == 200
    reply = probe.post("/probe", headers=_bearer(token))
    assert reply.status_code == 403
    assert "read-only" in reply.json()["detail"]


def test_unknown_key_is_rejected(db_session, user):
    reply = _probe(db_session).get("/probe", headers=_bearer(KEY_PREFIX + "nope"))
    assert reply.status_code == 401
    assert reply.json()["detail"] == "Invalid API key."


def test_expired_key_is_rejected(client, credentials, db_session):
    headers = _login(client, credentials)
    token = _create(client, headers, expires_in_days=1)["token"]
    key = db_session.scalar(select(ApiKey))
    key.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    assert _probe(db_session).get("/probe", headers=_bearer(token)).status_code == 401


def test_deleted_key_stops_working(client, credentials, db_session):
    headers = _login(client, credentials)
    created = _create(client, headers)
    assert client.delete(f"/api/api-keys/{created['id']}", headers=headers).status_code == 204
    assert _probe(db_session).get("/probe", headers=_bearer(created["token"])).status_code == 401


def test_key_of_a_disabled_user_is_rejected(client, credentials, db_session, user):
    headers = _login(client, credentials)
    token = _create(client, headers)["token"]
    user.disabled_at = datetime.now(UTC)
    db_session.commit()
    assert _probe(db_session).get("/probe", headers=_bearer(token)).status_code == 401


def test_other_bearer_tokens_fall_back_to_the_session(db_session, user):
    reply = _probe(db_session).get("/probe", headers=_bearer("abc"))
    assert reply.status_code == 401
    assert reply.json()["detail"] == "Not signed in."


def test_key_cannot_reach_cookie_only_endpoints(client, credentials):
    headers = _login(client, credentials)
    token = _create(client, headers)["token"]
    client.cookies.clear()
    for path in (
        "/api/auth/me",
        "/api/api-keys",
        "/api/users",
        "/api/admin/overview",
        "/api/nodes",
    ):
        reply = client.get(path, headers=_bearer(token))
        assert reply.status_code == 401, path
