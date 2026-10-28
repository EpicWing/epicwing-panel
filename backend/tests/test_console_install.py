import asyncio
import uuid

import pytest

from app.agentlink.console import ConsoleHub


class _Result:
    def __init__(self, ok: bool, error: str | None = None) -> None:
        self.ok = ok
        self.error = error


class _Commands:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    async def send(self, node_id, action, params, timeout=None):
        return _Result(self.ok, None if self.ok else "no such container")


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def test_install_output_is_replayed_to_the_first_browser():
    async def run():
        hub = ConsoleHub(_Commands())
        await hub.publish_install("srv", "one\n")
        await hub.publish_install("srv", "two\n")
        ws = _Socket()
        await hub.subscribe("srv", uuid.uuid4(), ws)
        return ws.sent

    assert asyncio.run(run()) == [
        {"type": "output", "data": "one\n"},
        {"type": "output", "data": "two\n"},
    ]


def test_install_output_is_forwarded_live_and_reset_clears():
    async def run():
        hub = ConsoleHub(_Commands())
        ws = _Socket()
        await hub.subscribe("srv", uuid.uuid4(), ws)
        await hub.publish_install("srv", "live\n")
        hub.start_install("srv")
        late = _Socket()
        await hub.subscribe("srv", uuid.uuid4(), late)
        return ws.sent, late.sent

    live, late = asyncio.run(run())
    assert live == [{"type": "output", "data": "live\n"}]
    assert late == []


def test_failing_watch_is_tolerated_only_during_install():
    async def run(with_install: bool):
        hub = ConsoleHub(_Commands(ok=False))
        if with_install:
            await hub.publish_install("srv", "x\n")
        await hub.subscribe("srv", uuid.uuid4(), _Socket())

    asyncio.run(run(True))
    with pytest.raises(Exception):
        asyncio.run(run(False))


def test_clear_empties_buffers_and_notifies_browsers():
    async def run():
        hub = ConsoleHub(_Commands())
        await hub.publish_install("srv", "old\n")
        ws = _Socket()
        await hub.subscribe("srv", uuid.uuid4(), ws)
        ws.sent.clear()
        await hub.publish_clear("srv")
        late = _Socket()
        await hub.subscribe("srv", uuid.uuid4(), late)
        return ws.sent, late.sent

    live, late = asyncio.run(run())
    assert live == [{"type": "clear"}]
    assert late == []
