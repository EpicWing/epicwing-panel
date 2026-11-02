import asyncio

import pytest

import app.agentlink.console as console_module
from app.agentlink.console import ConsoleHub


class _FailingCommands:
    """Die Node meldet, dass der Container nicht existiert."""

    async def send(self, node_id, action, params, timeout=None):
        return type("Result", (), {"ok": False, "error": "no such object", "code": None})()


class _Socket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def test_subscribe_during_install_survives_failed_watch():
    async def scenario():
        hub = ConsoleHub(_FailingCommands())
        hub.start_install("srv")  # buffer is still empty
        socket = _Socket()
        await hub.subscribe("srv", object(), socket)
        assert socket in hub._subs["srv"]
        await hub.publish_install("srv", "steamcmd line\n")
        return socket.sent

    assert asyncio.run(scenario()) == [{"type": "output", "data": "steamcmd line\n"}]


def test_subscribe_without_install_still_fails_on_watch_error():
    async def scenario():
        hub = ConsoleHub(_FailingCommands())
        socket = _Socket()
        with pytest.raises(console_module.ConsoleError):
            await hub.subscribe("srv", object(), socket)
        assert "srv" not in hub._subs

    asyncio.run(scenario())
