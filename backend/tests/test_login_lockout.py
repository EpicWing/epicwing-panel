WRONG = "falsch-falsch-falsch"


def _login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _set_ip(monkeypatch, ip):
    monkeypatch.setattr("app.api.auth._client_ip", lambda request: ip)


def test_lockout_only_blocks_the_attacking_ip(client, credentials, monkeypatch):
    _set_ip(monkeypatch, "203.0.113.1")
    for _ in range(5):
        assert _login(client, credentials["email"], WRONG).status_code == 401
    # Der Angreifer ist gesperrt, auch mit richtigem Passwort.
    assert _login(client, credentials["email"], credentials["password"]).status_code == 429
    # Der echte Nutzer kommt von einer anderen IP weiterhin rein.
    _set_ip(monkeypatch, "203.0.113.2")
    assert _login(client, credentials["email"], credentials["password"]).status_code == 200


def test_successful_login_resets_failure_count(client, credentials, monkeypatch):
    _set_ip(monkeypatch, "203.0.113.3")
    for _ in range(4):
        assert _login(client, credentials["email"], WRONG).status_code == 401
    assert _login(client, credentials["email"], credentials["password"]).status_code == 200
    # Ohne Reset wäre hier beim sechsten Fehlversuch insgesamt Schluss.
    for _ in range(4):
        assert _login(client, credentials["email"], WRONG).status_code == 401
