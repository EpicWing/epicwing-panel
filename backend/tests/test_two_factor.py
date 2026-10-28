import types

import pyotp
import pytest

from app.security import totp
from app.security.sessions import create_session

PASSWORD = "correct-horse-battery"
EMAIL = "admin@example.test"
BASE = "/api/auth/2fa"


@pytest.fixture
def clock(monkeypatch):
    state = types.SimpleNamespace(t=1_800_000_000)
    monkeypatch.setattr(totp, "time", types.SimpleNamespace(time=lambda: state.t))
    return state


@pytest.fixture
def headers(client, user):
    response = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _bad_code(secret: str, t: int) -> str:
    valid = {pyotp.TOTP(secret).at(t + d) for d in (-30, 0, 30)}
    return next(f"{n:06d}" for n in range(1_000_000) if f"{n:06d}" not in valid)


def _setup(client, headers) -> str:
    response = client.post(f"{BASE}/setup", json={"password": PASSWORD}, headers=headers)
    assert response.status_code == 200
    return response.json()["secret"]


def _enable(client, headers, clock, secret) -> list[str]:
    code = pyotp.TOTP(secret).at(clock.t)
    response = client.post(f"{BASE}/enable", json={"code": code}, headers=headers)
    assert response.status_code == 200
    return response.json()["recovery_codes"]


def test_requires_login(client):
    assert client.get(BASE).status_code == 401


def test_setup_needs_correct_password(client, headers, user):
    response = client.post(f"{BASE}/setup", json={"password": "falsch"}, headers=headers)
    assert response.status_code == 400
    assert user.totp_secret is None


def test_setup_response(client, headers, db_session, user):
    response = client.post(f"{BASE}/setup", json={"password": PASSWORD}, headers=headers)
    body = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["qr_svg"].startswith("<svg")
    db_session.refresh(user)
    assert body["secret"] not in user.totp_secret


def test_full_flow(client, headers, clock):
    assert client.get(BASE).json() == {"enabled": False, "recovery_codes_remaining": 0}
    secret = _setup(client, headers)
    codes = _enable(client, headers, clock, secret)
    assert len(codes) == 10
    assert client.get(BASE).json() == {"enabled": True, "recovery_codes_remaining": 10}

    again = client.post(f"{BASE}/setup", json={"password": PASSWORD}, headers=headers)
    assert again.status_code == 409

    replay = {"password": PASSWORD, "code": pyotp.TOTP(secret).at(clock.t)}
    assert client.post(f"{BASE}/disable", json=replay, headers=headers).status_code == 400

    body = {"password": PASSWORD, "code": codes[0]}
    assert client.post(f"{BASE}/disable", json=body, headers=headers).status_code == 204
    assert client.get(BASE).json() == {"enabled": False, "recovery_codes_remaining": 0}


def test_enable_without_setup(client, headers):
    response = client.post(f"{BASE}/enable", json={"code": "123456"}, headers=headers)
    assert response.status_code == 409


def test_enable_with_wrong_code(client, headers, clock):
    secret = _setup(client, headers)
    bad = _bad_code(secret, clock.t)
    assert client.post(f"{BASE}/enable", json={"code": bad}, headers=headers).status_code == 400
    assert client.get(BASE).json()["enabled"] is False


def test_code_attempts_are_limited(client, headers, clock):
    secret = _setup(client, headers)
    bad = _bad_code(secret, clock.t)
    for _ in range(5):
        assert client.post(f"{BASE}/enable", json={"code": bad}, headers=headers).status_code == 400
    good = pyotp.TOTP(secret).at(clock.t)
    blocked = client.post(f"{BASE}/enable", json={"code": good}, headers=headers)
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers


def test_regenerate_invalidates_old_codes(client, headers, clock):
    secret = _setup(client, headers)
    old = _enable(client, headers, clock, secret)
    clock.t += 30
    body = {"password": PASSWORD, "code": pyotp.TOTP(secret).at(clock.t)}
    response = client.post(f"{BASE}/recovery-codes", json=body, headers=headers)
    assert response.status_code == 200
    new = response.json()["recovery_codes"]
    assert len(new) == 10 and set(new).isdisjoint(old)

    stale = {"password": PASSWORD, "code": old[0]}
    assert client.post(f"{BASE}/disable", json=stale, headers=headers).status_code == 400
    fresh = {"password": PASSWORD, "code": new[0]}
    assert client.post(f"{BASE}/disable", json=fresh, headers=headers).status_code == 204


def test_enable_revokes_other_sessions(client, headers, clock, db_session, user):
    _, other = create_session(db_session, user, "127.0.0.1", None)
    secret = _setup(client, headers)
    _enable(client, headers, clock, secret)
    db_session.refresh(other)
    assert other.revoked_at is not None
    assert client.get(BASE).status_code == 200
