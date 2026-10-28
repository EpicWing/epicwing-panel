from datetime import UTC, datetime

WRONG = "falsch-falsch-falsch"


def _login(client, credentials):
    return client.post("/api/auth/login", json=credentials)


def test_me_requires_login(client):
    assert client.get("/api/auth/me").status_code == 401


def test_login_sets_cookie_and_csrf_token(client, credentials):
    response = _login(client, credentials)
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == credentials["email"]
    assert body["csrf_token"]
    assert "httponly" in response.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(client, credentials):
    wrong = client.post("/api/auth/login", json={**credentials, "password": WRONG})
    unknown = client.post(
        "/api/auth/login", json={"email": "niemand@example.test", "password": WRONG}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert "set-cookie" not in wrong.headers


def test_logout_needs_csrf_token(client, credentials):
    _login(client, credentials)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.get("/api/auth/me").status_code == 200


def test_logout_ends_session(client, credentials):
    csrf = _login(client, credentials).json()["csrf_token"]
    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_login_rate_limit(client, credentials):
    for _ in range(5):
        response = client.post("/api/auth/login", json={**credentials, "password": WRONG})
        assert response.status_code == 401
    response = _login(client, credentials)
    assert response.status_code == 429
    assert "retry-after" in response.headers


def test_disabled_user_cannot_login(client, db_session, user, credentials):
    user.disabled_at = datetime.now(UTC)
    db_session.commit()
    assert _login(client, credentials).status_code == 401


def test_foreign_origin_is_rejected(client, credentials):
    response = client.post(
        "/api/auth/login", json=credentials, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
