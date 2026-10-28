import asyncio

from app.services import ddos_alerts


def test_cooldown_per_server(monkeypatch):
    sent = []
    monkeypatch.setattr(ddos_alerts, "_deliver", lambda name, reasons: sent.append(name))
    ddos_alerts._last_alert.clear()

    async def scenario():
        assert ddos_alerts.schedule("a", ["x"], now=100.0)
        assert not ddos_alerts.schedule("a", ["x"], now=160.0)
        assert ddos_alerts.schedule("b", [], now=110.0)
        assert ddos_alerts.schedule("a", ["x"], now=101.0 + ddos_alerts.COOLDOWN_SECONDS)
        await asyncio.gather(*list(ddos_alerts._tasks))

    asyncio.run(scenario())
    assert sorted(sent) == ["a", "a", "b"]
