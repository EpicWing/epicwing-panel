import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.api import password_reset as reset_api
from app.models import PasswordResetToken
from app.security.ratelimit import (
    login_email_limiter,
    reset_confirm_ip_limiter,
    reset_request_email_limiter,
    reset_request_ip_limiter,
)
from app.services import mail

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "a-brand-new-passphrase"
AVAILABLE = "/api/auth/password-reset/available"
REQUEST = "/api/auth/password-reset/request"
CONFIRM = "/api/auth/password-reset/confirm"
TOKEN = re.compile(r"#token=([A-Za-z0-9_-]+)")


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    for limiter in (
        reset_request_ip_limiter,
        reset_request_email_limiter,
        reset_confirm_ip_limiter,
    ):
        limiter.clear()
    sent: list[dict] = []
    config = SimpleNamespace(sender="EpicWing <noreply@example.test>", reply_to="", provider="smtp")
    monkeypatch.setattr(mail, "load_config", lambda db: config)
    monkeypatch.setattr(mail, "is_configured", lambda cfg: True)

    def fake_send(to, subject, html, text, config=None):
        sent.append({"to": to, "subject": subject, "html": html, "text": text})
        return True, "test"

    monkeypatch.setattr(mail, "send_mail", fake_send)
    monkeypatch.setattr(
        reset_api, "get_settings", lambda: SimpleNamespace(public_origin="https://panel.test")
    )
    return sent


def _token(outbox) -> str:
    last = outbox[-1]
    found = TOKEN.search(last["text"] + last["html"])
    assert found, "no reset link in the mail"
    return found.group(1)


def _confirm(client, token: str, password: str = NEW_PASSWORD):
    return client.post(CONFIRM, json={"token": token, "new_password": password})


def test_available_when_mail_and_url_are_set(client):
    assert client.get(AVAILABLE).json() == {"available": True}


def test_not_available_without_mail(client, monkeypatch):
    monkeypatch.setattr(mail, "is_configured", lambda cfg: False)
    assert client.get(AVAILABLE).json() == {"available": False}
    assert client.post(REQUEST, json={"email": "admin@example.test"}).status_code == 503


def test_not_available_without_public_url(client, monkeypatch):
    monkeypatch.setattr(reset_api, "get_settings", lambda: SimpleNamespace(public_origin=""))
    assert client.get(AVAILABLE).json() == {"available": False}


def test_same_answer_for_known_and_unknown_address(client, user, outbox):
    known = client.post(REQUEST, json={"email": user.email})
    unknown = client.post(REQUEST, json={"email": "nobody@example.test"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(outbox) == 1
    assert outbox[0]["to"] == user.email


def test_mail_contains_link_with_fixed_origin(client, user, outbox):
    client.post(REQUEST, json={"email": user.email.upper()})
    assert "https://panel.test/reset-password#token=" in outbox[0]["text"] + outbox[0]["html"]


def test_token_is_stored_hashed(client, user, outbox, db_session):
    client.post(REQUEST, json={"email": user.email})
    token = _token(outbox)
    row = db_session.scalar(select(PasswordResetToken))
    assert row.token_hash != token
    assert len(row.token_hash) == 64


def test_disabled_account_gets_no_mail(client, user, outbox, db_session):
    user.disabled_at = datetime.now(UTC)
    db_session.commit()
    assert client.post(REQUEST, json={"email": user.email}).status_code == 202
    assert outbox == []


def test_reset_sets_new_password(client, user, outbox):
    client.post(REQUEST, json={"email": user.email})
    response = client.post(CONFIRM, json={"token": _token(outbox), "new_password": NEW_PASSWORD})
    assert response.status_code == 204
    old = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert old.status_code == 401
    new = client.post("/api/auth/login", json={"email": user.email, "password": NEW_PASSWORD})
    assert new.status_code == 200


def test_token_works_only_once(client, user, outbox):
    client.post(REQUEST, json={"email": user.email})
    token = _token(outbox)
    assert _confirm(client, token).status_code == 204
    again = client.post(CONFIRM, json={"token": token, "new_password": "another-passphrase-1"})
    assert again.status_code == 400


def test_new_request_invalidates_old_link(client, user, outbox):
    client.post(REQUEST, json={"email": user.email})
    first = _token(outbox)
    client.post(REQUEST, json={"email": user.email})
    second = _token(outbox)
    assert first != second
    assert _confirm(client, first).status_code == 400
    assert _confirm(client, second).status_code == 204


def test_expired_token_is_rejected(client, user, outbox, db_session):
    client.post(REQUEST, json={"email": user.email})
    row = db_session.scalar(select(PasswordResetToken))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    response = client.post(CONFIRM, json={"token": _token(outbox), "new_password": NEW_PASSWORD})
    assert response.status_code == 400


def test_garbage_token_is_rejected(client):
    response = client.post(CONFIRM, json={"token": "x" * 43, "new_password": NEW_PASSWORD})
    assert response.status_code == 400


def test_short_password_keeps_the_link_valid(client, user, outbox):
    client.post(REQUEST, json={"email": user.email})
    token = _token(outbox)
    assert client.post(CONFIRM, json={"token": token, "new_password": "short"}).status_code == 422
    assert _confirm(client, token).status_code == 204


def test_reset_ends_all_sessions(client, user, outbox):
    login = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert login.status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    client.post(REQUEST, json={"email": user.email})
    client.post(CONFIRM, json={"token": _token(outbox), "new_password": NEW_PASSWORD})
    assert client.get("/api/auth/me").status_code == 401


def test_reset_lifts_login_lockout(client, user, outbox):
    for _ in range(5):
        login_email_limiter.add_failure(user.email)
    assert login_email_limiter.retry_after(user.email) > 0
    client.post(REQUEST, json={"email": user.email})
    client.post(CONFIRM, json={"token": _token(outbox), "new_password": NEW_PASSWORD})
    assert login_email_limiter.retry_after(user.email) == 0


def test_mail_flood_per_address_is_limited_silently(client, user, outbox):
    for _ in range(4):
        assert client.post(REQUEST, json={"email": user.email}).status_code == 202
    assert len(outbox) == 3


def test_requests_per_ip_are_limited(client):
    for index in range(10):
        assert client.post(REQUEST, json={"email": f"user{index}@example.test"}).status_code == 202
    assert client.post(REQUEST, json={"email": "one-more@example.test"}).status_code == 429
