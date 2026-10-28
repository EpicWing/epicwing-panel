import asyncio
import uuid

from app.services import node_alerts as na


def _patch(monkeypatch, status: str) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(na, "_node_info", lambda node_id: (status, "node-1"))
    monkeypatch.setattr(na, "_deliver", lambda title, text: sent.append(title))
    return sent


def test_offline_alert_and_recovery(monkeypatch):
    sent = _patch(monkeypatch, "offline")
    node_id = uuid.uuid4()

    async def run():
        na.schedule_offline_alert(node_id, delay=0)
        await asyncio.sleep(0.1)
        await na.on_node_online(node_id)

    asyncio.run(run())
    assert sent == ["Node offline", "Node back online"]


def test_reconnect_within_grace_sends_nothing(monkeypatch):
    sent = _patch(monkeypatch, "offline")
    node_id = uuid.uuid4()

    async def run():
        na.schedule_offline_alert(node_id, delay=0.3)
        await na.on_node_online(node_id)
        await asyncio.sleep(0.5)

    asyncio.run(run())
    assert sent == []


def test_node_back_online_before_check_sends_nothing(monkeypatch):
    sent = _patch(monkeypatch, "online")
    node_id = uuid.uuid4()

    async def run():
        na.schedule_offline_alert(node_id, delay=0)
        await asyncio.sleep(0.1)
        await na.on_node_online(node_id)

    asyncio.run(run())
    assert sent == []
