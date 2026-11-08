import httpx
import pytest

from app.services import notify


@pytest.mark.parametrize(
    "url",
    [
        "https://discord.com/api/webhooks/1/abc",
        "https://discordapp.com/api/webhooks/1/abc",
        "https://ptb.discord.com/api/webhooks/1/abc",
    ],
)
def test_accepts_discord_webhooks(url):
    assert notify._is_discord_webhook(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://discord.com/api/webhooks/1/abc",
        "https://discord.com.evil.example/api/webhooks/1/abc",
        "https://notdiscord.com/api/webhooks/1/abc",
        "https://discord.com@evil.example/api/webhooks/1/abc",
        "https://evil.example/https://discord.com/api/webhooks/1/abc",
        "https://discord.com:8443/api/webhooks/1/abc",
        "https://127.0.0.1/api/webhooks/1/abc",
        "https://discord.com/other",
    ],
)
def test_rejects_other_urls(url):
    assert not notify._is_discord_webhook(url)


def test_send_discord_does_not_call_other_hosts(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("no request may be made")

    monkeypatch.setattr(httpx, "post", fail)
    ok, _detail = notify.send_discord("https://127.0.0.1/api/webhooks/1/abc", "t", "x")
    assert ok is False
