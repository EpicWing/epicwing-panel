from types import SimpleNamespace

import pytest

from app.api import admin_mail
from app.models import PanelSetting
from app.security import vault
from app.services import mail

PASSWORD = "correct-horse-battery"
URL = "/api/admin/mail"
VALID = {
    "provider": "resend",
    "sender": "EpicWing <noreply@example.com>",
    "reply_to": "support@example.com",
    "discord_url": "https://discord.gg/abc",
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_security": "starttls",
    "resend_api_key": "re_secret_value",
}


@pytest.fixture(autouse=True)
def no_env_mail(monkeypatch):
    monkeypatch.setattr(
        mail,
        "get_settings",
        lambda: SimpleNamespace(resend_api_key="", mail_from="", mail_reply_to=""),
    )


@pytest.fixture
def headers(client, user):
    response = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_vault_roundtrip_and_purpose_isolation():
    token = vault.encrypt_text("hello", "mail")
    assert vault.decrypt_text(token, "mail") == "hello"
    assert vault.decrypt_text(token, "totp") is None
    assert vault.decrypt_text("garbage", "mail") is None


def test_load_config_falls_back_to_env(db_session, monkeypatch):
    monkeypatch.setattr(
        mail,
        "get_settings",
        lambda: SimpleNamespace(
            resend_api_key="re_env", mail_from="Env <e@example.com>", mail_reply_to=""
        ),
    )
    config = mail.load_config(db_session)
    assert (config.provider, config.resend_api_key, config.sender) == (
        "resend",
        "re_env",
        "Env <e@example.com>",
    )


def test_save_config_encrypts_secrets(db_session):
    mail.save_config(
        db_session,
        {"provider": "smtp", "smtp_host": "h", "smtp_password": "secret-pw", "sender": "x@e.com"},
    )
    stored = db_session.get(PanelSetting, "mail.smtp_password").value
    assert stored and "secret-pw" not in stored
    config = mail.load_config(db_session)
    assert (config.provider, config.smtp_host, config.smtp_password) == ("smtp", "h", "secret-pw")


def test_get_requires_login(client):
    assert client.get(URL).status_code == 401


def test_get_never_returns_secrets(client, headers):
    response = client.get(URL)
    assert response.status_code == 200
    body = response.json()
    assert body["resend_api_key_set"] is False and body["configured"] is False
    assert "resend_api_key" not in body and "smtp_password" not in body


def test_save_and_read_back(client, headers):
    response = client.put(URL, json=VALID, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sender"] == VALID["sender"]
    assert body["resend_api_key_set"] is True and body["configured"] is True
    assert "re_secret_value" not in response.text
    assert "re_secret_value" not in client.get(URL).text


def test_save_keeps_secret_when_omitted(client, headers):
    client.put(URL, json=VALID, headers=headers)
    response = client.put(URL, json=dict(VALID, resend_api_key=None, reply_to=""), headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["resend_api_key_set"] is True
    assert response.json()["reply_to"] == ""


@pytest.mark.parametrize(
    "patch",
    [
        {"sender": "not-an-address"},
        {"sender": ""},
        {"sender": "a@example.com\r\nBcc: b@example.com"},
        {"reply_to": "nope"},
        {"discord_url": "javascript:alert(1)"},
        {"provider": "sendmail"},
        {"smtp_port": 0},
    ],
)
def test_save_rejects_invalid_input(client, headers, patch):
    response = client.put(URL, json=dict(VALID, **patch), headers=headers)
    assert response.status_code == 422


def test_test_mail_uses_saved_settings(client, headers, monkeypatch):
    sent = {}

    def fake_send(to, subject, html, text, config=None):
        sent.update(to=to, html=html, config=config)
        return True, "msg-1"

    monkeypatch.setattr(admin_mail, "send_mail", fake_send)
    client.put(URL, json=VALID, headers=headers)
    response = client.post(f"{URL}/test", json={"to": "me@example.com"}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "detail": "msg-1"}
    assert sent["to"] == "me@example.com"
    assert "https://discord.gg/abc" in sent["html"]
    assert sent["config"].resend_api_key == "re_secret_value"


def test_test_mail_reports_failure(client, headers, monkeypatch):
    monkeypatch.setattr(admin_mail, "send_mail", lambda *a, **k: (False, "HTTP 403: nope"))
    response = client.post(f"{URL}/test", json={"to": "me@example.com"}, headers=headers)
    assert response.json() == {"ok": False, "detail": "HTTP 403: nope"}


def test_test_mail_rejects_bad_recipient(client, headers):
    assert client.post(f"{URL}/test", json={"to": "nobody"}, headers=headers).status_code == 422
