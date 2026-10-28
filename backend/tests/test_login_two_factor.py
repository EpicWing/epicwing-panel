import types
from datetime import UTC, datetime

import pyotp
import pytest

from app.security import challenge as challenge_module
from app.security import totp
from app.security.passwords import hash_password

PASSWORD = "correct-horse-battery"
EMAIL = "admin@example.test"


@pytest.fixture
def clock(monkeypatch):
    state = types.SimpleNamespace(t=1_800_000_000)
    fake = types.SimpleNamespace(time=lambda: state.t)
    monkeypatch.setattr(totp, "time", fake)
    monkeypatch.setattr(challenge_module, "time", fake)
    return state


@pytest.fixture
def secured(db_session, user, clock):
    secret = totp.begin_enrollment(db_session, user)
    assert totp.verify_code(db_session, user, pyotp.TOTP(secret).at(clock.t))
    codes = totp.activate(db_session, user)
    clock.t += 30
    return types.SimpleNamespace(secret=secret, codes=codes)


def _login(client):
    return client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})


def _second(client, challenge, code):
    return client.post("/api/auth/login/2fa", json={"challenge": challenge, "code": code})


def _code(secured, clock):
    return pyotp.TOTP(secured.secret).at(clock.t)


def _bad_code(secured, clock):
    valid = {pyotp.TOTP(secured.secret).at(clock.t + d) for d in (-30, 0, 30)}
    return next(f"{n:06d}" for n in range(1_000_000) if f"{n:06d}" not in valid)


def test_password_alone_gives_no_session(client, secured):
    response = _login(client)
    body = response.json()
    assert response.status_code == 200
    assert body["two_factor_required"] is True and body["challenge"]
    assert "csrf_token" not in body
    assert client.get("/api/auth/me").status_code == 401


def test_second_factor_completes_login(client, secured, clock):
    challenge = _login(client).json()["challenge"]
    response = _second(client, challenge, _code(secured, clock))
    assert response.status_code == 200
    assert response.json()["user"]["email"] == EMAIL
    assert client.get("/api/auth/me").status_code == 200


def test_wrong_code_gives_no_session(client, secured, clock):
    challenge = _login(client).json()["challenge"]
    assert _second(client, challenge, _bad_code(secured, clock)).status_code == 400
    assert client.get("/api/auth/me").status_code == 401
    assert _second(client, challenge, _code(secured, clock)).status_code == 200


def test_code_cannot_be_replayed(client, secured, clock):
    code = _code(secured, clock)
    first = _login(client).json()["challenge"]
    ok = _second(client, first, code)
    assert ok.status_code == 200
    client.post("/api/auth/logout", headers={"X-CSRF-Token": ok.json()["csrf_token"]})
    second = _login(client).json()["challenge"]
    assert _second(client, second, code).status_code == 400
    clock.t += 30
    assert _second(client, second, _code(secured, clock)).status_code == 200


def test_recovery_code_works_once(client, secured):
    code = secured.codes[0]
    assert _second(client, _login(client).json()["challenge"], code).status_code == 200
    assert _second(client, _login(client).json()["challenge"], code).status_code == 400


def test_expired_challenge(client, secured, clock):
    challenge = _login(client).json()["challenge"]
    clock.t += 301
    assert _second(client, challenge, _code(secured, clock)).status_code == 401


def test_tampered_challenge(client, secured, clock):
    challenge = _login(client).json()["challenge"]
    flipped = challenge[:-1] + ("0" if challenge[-1] != "0" else "1")
    assert _second(client, flipped, _code(secured, clock)).status_code == 401
    assert _second(client, "garbage", _code(secured, clock)).status_code == 401


def test_password_change_kills_challenge(client, db_session, user, secured, clock):
    challenge = _login(client).json()["challenge"]
    user.password_hash = hash_password("another-long-password")
    db_session.commit()
    assert _second(client, challenge, _code(secured, clock)).status_code == 401


def test_disabled_user_cannot_finish(client, db_session, user, secured, clock):
    challenge = _login(client).json()["challenge"]
    user.disabled_at = datetime.now(UTC)
    db_session.commit()
    assert _second(client, challenge, _code(secured, clock)).status_code == 401


def test_challenge_without_2fa_is_useless(client, user, clock):
    challenge = challenge_module.make_challenge(user)
    assert _second(client, challenge, "123456").status_code == 401


def test_attempts_are_limited(client, secured, clock):
    challenge = _login(client).json()["challenge"]
    bad = _bad_code(secured, clock)
    for _ in range(5):
        assert _second(client, challenge, bad).status_code == 400
    blocked = _second(client, challenge, _code(secured, clock))
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers
