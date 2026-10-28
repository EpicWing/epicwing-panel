import smtplib

import httpx
import pytest

from app.services import mail
from app.services.mail import MailConfig


def _config(**overrides) -> MailConfig:
    values = {
        "provider": "resend",
        "resend_api_key": "re_test",
        "sender": "EpicWing <noreply@example.com>",
        "reply_to": "support@example.com",
    }
    values.update(overrides)
    return MailConfig(**values)


def _send(config):
    return mail.send_mail("to@example.com", "Subject", "<p>x</p>", "plain", config)


def test_render_has_layout_and_text_part():
    html, text = mail.render("Hello", ["First", "Second"], ("Open", "https://example.com/x"))
    assert "EpicWing" in html and "Hello" in html and "First" in html
    assert 'href="https://example.com/x"' in html
    assert "Hello" in text and "Open: https://example.com/x" in text


def test_render_without_button():
    html, text = mail.render("Hi", ["Body"])
    assert html.count("<a ") == 2  # nur die Footer-Links, kein Button
    assert "Open" not in text


def test_render_escapes_content():
    html, _ = mail.render("<b>x</b>", ["<script>alert(1)</script>"])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_rejects_non_http_button():
    with pytest.raises(ValueError):
        mail.render("T", ["p"], ("Go", "javascript:alert(1)"))


def test_footer_depends_on_settings():
    html, _ = mail.render("T", ["p"], reply_hint=True)
    assert "Reply to this email" in html
    html, _ = mail.render("T", ["p"])
    assert "Reply" not in html and "Discord" not in html


def test_render_for_uses_config():
    html, _ = mail.render_for(_config(), "T", ["p"])
    assert "Reply to this email" in html
    html, _ = mail.render_for(_config(reply_to=""), "T", ["p"])
    assert "Reply" not in html


def test_send_needs_a_sender():
    ok, info = _send(_config(sender=""))
    assert not ok and "sender" in info


def test_send_needs_a_key():
    ok, info = _send(_config(resend_api_key=""))
    assert not ok and "API key" in info


def test_send_posts_to_resend(monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json)
        return httpx.Response(200, json={"id": "abc"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(mail.httpx, "post", fake_post)
    assert _send(_config()) == (True, "abc")
    assert seen["url"] == mail.API_URL
    assert seen["headers"]["Authorization"] == "Bearer re_test"
    assert seen["json"]["from"] == "EpicWing <noreply@example.com>"
    assert seen["json"]["to"] == ["to@example.com"]
    assert seen["json"]["reply_to"] == "support@example.com"


def test_send_omits_empty_reply_to(monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(json=json)
        return httpx.Response(200, json={"id": "abc"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(mail.httpx, "post", fake_post)
    assert _send(_config(reply_to=""))[0] is True
    assert "reply_to" not in seen["json"]


def test_send_reports_http_errors(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return httpx.Response(403, text="domain not verified", request=httpx.Request("POST", url))

    monkeypatch.setattr(mail.httpx, "post", fake_post)
    ok, info = _send(_config())
    assert not ok and info.startswith("HTTP 403")


def test_send_survives_network_errors(monkeypatch):
    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(mail.httpx, "post", fake_post)
    ok, info = _send(_config())
    assert not ok and "ConnectError" in info


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.context = host, port, context
        self.calls: list = []
        self.message = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, message):
        self.message = message


def _smtp_config(**overrides) -> MailConfig:
    values = {
        "provider": "smtp",
        "smtp_host": "mail.example.com",
        "smtp_port": 587,
        "smtp_user": "u",
        "smtp_password": "p",
        "smtp_security": "starttls",
    }
    values.update(overrides)
    return _config(**values)


def test_send_via_smtp_starttls(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    ok, _ = _send(_smtp_config())
    assert ok
    client = FakeSMTP.instances[0]
    assert (client.host, client.port) == ("mail.example.com", 587)
    assert client.calls == ["starttls", ("login", "u", "p")]
    assert client.message["To"] == "to@example.com"
    assert client.message["Subject"] == "Subject"
    assert client.message["Reply-To"] == "support@example.com"


def test_send_via_smtp_ssl_without_login(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    ok, _ = _send(_smtp_config(smtp_security="ssl", smtp_port=465, smtp_user=""))
    assert ok
    client = FakeSMTP.instances[0]
    assert client.port == 465 and client.calls == []


def test_smtp_reports_login_errors(monkeypatch):
    class BrokenSMTP(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"nope")

    monkeypatch.setattr(mail.smtplib, "SMTP", BrokenSMTP)
    ok, info = _send(_smtp_config())
    assert not ok and "SMTPAuthenticationError" in info


def test_smtp_needs_a_host():
    ok, info = _send(_smtp_config(smtp_host=""))
    assert not ok and "host" in info


def test_smtp_rejects_header_injection(monkeypatch):
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    ok, _ = mail.send_mail(
        "a@example.com\r\nBcc: b@example.com", "S", "<p>x</p>", "x", _smtp_config()
    )
    assert ok is False
