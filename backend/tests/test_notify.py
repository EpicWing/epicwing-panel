import httpx

from app.services import notify as n


def _settings() -> n.NotifySettings:
    return n.NotifySettings(True, "https://discord.com/api/webhooks/1/x", True, "a@example.com")


def test_failing_channel_does_not_block_the_other(monkeypatch):
    sent: list[str] = []

    def boom(*args, **kwargs):
        raise RuntimeError("down")

    def fake_email(db, to, title, text):
        sent.append(to)
        return True, "OK"

    monkeypatch.setattr(n, "load_settings", lambda db: _settings())
    monkeypatch.setattr(n, "send_discord", boom)
    monkeypatch.setattr(n, "send_email", fake_email)
    result = n.notify(None, "Node offline", "node-1")  # type: ignore[arg-type]
    assert result["discord"][0] is False
    assert result["email"] == (True, "OK")
    assert sent == ["a@example.com"]


def test_disabled_channels_are_skipped(monkeypatch):
    url = "https://discord.com/api/webhooks/1/x"
    settings = n.NotifySettings(False, url, False, "a@example.com")
    monkeypatch.setattr(n, "load_settings", lambda db: settings)
    assert n.notify(None, "t", "x") == {}  # type: ignore[arg-type]


def test_discord_error_detail_never_contains_the_url(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("https://discord.com/api/webhooks/SECRET")

    monkeypatch.setattr(n.httpx, "post", fail)
    ok, detail = n.send_discord("https://discord.com/api/webhooks/SECRET", "t", "x")
    assert ok is False
    assert "SECRET" not in detail
