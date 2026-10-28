from types import SimpleNamespace

import httpx
import pytest

from app.services import mail


def _settings(key="re_test"):
    return SimpleNamespace(
        resend_api_key=key,
        mail_from="EpicWing <noreply@example.test>",
        mail_reply_to="support@example.test",
    )


class _Response:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


def test_render_has_layout_and_text_part():
    html, text = mail.render("Hello", ["First", "Second"], ("Open", "https://example.test/x"))
    assert "EpicWing" in html
    assert mail.DISCORD_URL in html
    assert "Copyright &copy;" in html
    assert 'href="https://example.test/x"' in html
    assert "First" in text
    assert "Second" in text
    assert mail.DISCORD_URL in text
    assert "https://example.test/x" in text


def test_render_without_button():
    html, text = mail.render("Hello", ["Only text"])
    assert "Only text" in html
    assert "bgcolor" not in html
    assert "Only text" in text


def test_render_escapes_content():
    html, text = mail.render("<b>x</b>", ["<script>alert(1)</script>"])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>x</b>" not in html


def test_render_rejects_non_http_button():
    with pytest.raises(ValueError):
        mail.render("t", ["p"], ("Go", "javascript:alert(1)"))


def test_send_needs_a_key(monkeypatch):
    monkeypatch.setattr(mail, "get_settings", lambda: _settings(""))
    ok, info = mail.send_mail("a@example.test", "s", "<p>h</p>", "t")
    assert not ok
    assert "RESEND_API_KEY" in info


def test_send_posts_to_resend(monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json)
        return _Response(200, {"id": "abc"})

    monkeypatch.setattr(mail, "get_settings", lambda: _settings())
    monkeypatch.setattr(mail.httpx, "post", fake_post)
    ok, info = mail.send_mail("a@example.test", "Subject", "<p>h</p>", "t")
    assert ok
    assert info == "abc"
    assert seen["url"] == mail.API_URL
    assert seen["headers"]["Authorization"] == "Bearer re_test"
    assert seen["json"]["to"] == ["a@example.test"]
    assert seen["json"]["from"] == "EpicWing <noreply@example.test>"
    assert seen["json"]["reply_to"] == "support@example.test"
    assert seen["json"]["subject"] == "Subject"


def test_send_reports_http_errors(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return _Response(403, text='{"message":"domain is not verified"}')

    monkeypatch.setattr(mail, "get_settings", lambda: _settings())
    monkeypatch.setattr(mail.httpx, "post", fake_post)
    ok, info = mail.send_mail("a@example.test", "s", "<p>h</p>", "t")
    assert not ok
    assert "403" in info
    assert "re_test" not in info


def test_send_survives_network_errors(monkeypatch):
    def fake_post(url, headers, json, timeout):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(mail, "get_settings", lambda: _settings())
    monkeypatch.setattr(mail.httpx, "post", fake_post)
    ok, info = mail.send_mail("a@example.test", "s", "<p>h</p>", "t")
    assert not ok
    assert "ConnectError" in info
