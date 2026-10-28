import asyncio
import uuid

import pytest

from app.agentlink.commands import AgentOffline, CommandBroker
from app.agentlink.protocol import CommandResult
from app.agentlink.registry import AgentRegistry
from tests.test_agent_ws import HEARTBEAT, WS_URL, _enroll_node, _login_agent


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = None

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000):
        self.closed = code


async def _first_command(ws):
    for _ in range(100):
        if ws.sent:
            return ws.sent[0]
        await asyncio.sleep(0.01)
    raise AssertionError("no command was sent")


async def _setup():
    agents = AgentRegistry()
    node = uuid.uuid4()
    ws = FakeSocket()
    await agents.register(node, ws)
    return CommandBroker(agents), node, ws


def _ok(command_id):
    return CommandResult(type="result", id=command_id, ok=True, data={"id": "abc"})


def test_send_returns_the_result():
    async def scenario():
        broker, node, ws = await _setup()
        task = asyncio.create_task(broker.send(node, "container.stop", {"name": "web-1"}, 2))
        command = await _first_command(ws)
        assert command["type"] == "command"
        assert command["action"] == "container.stop"
        assert command["params"] == {"name": "web-1"}
        assert broker.resolve(node, _ok(command["id"]))
        result = await task
        assert result.ok
        assert result.data == {"id": "abc"}
        assert not broker._pending

    asyncio.run(scenario())


def test_send_to_offline_node_fails():
    async def scenario():
        broker = CommandBroker(AgentRegistry())
        with pytest.raises(AgentOffline):
            await broker.send(uuid.uuid4(), "container.start", {})

    asyncio.run(scenario())


def test_unknown_action_is_refused():
    async def scenario():
        broker, node, ws = await _setup()
        with pytest.raises(ValueError, match="unknown action"):
            await broker.send(node, "shell.run", {})
        assert not ws.sent

    asyncio.run(scenario())


def test_result_from_another_node_is_ignored():
    async def scenario():
        broker, node, ws = await _setup()
        task = asyncio.create_task(broker.send(node, "container.start", {}, 2))
        command = await _first_command(ws)
        assert not broker.resolve(uuid.uuid4(), _ok(command["id"]))
        assert broker.resolve(node, _ok(command["id"]))
        await task

    asyncio.run(scenario())


def test_lost_connection_fails_pending_commands():
    async def scenario():
        broker, node, ws = await _setup()
        task = asyncio.create_task(broker.send(node, "container.start", {}, 5))
        await _first_command(ws)
        broker.fail_pending(node)
        with pytest.raises(AgentOffline):
            await task

    asyncio.run(scenario())


def test_command_times_out_and_cleans_up():
    async def scenario():
        broker, node, _ws = await _setup()
        with pytest.raises(TimeoutError):
            await broker.send(node, "container.start", {}, 0.05)
        assert not broker._pending

    asyncio.run(scenario())


def test_unknown_result_frame_is_ignored(client, user):
    node_id, key = _enroll_node(client, user)
    with client.websocket_connect(WS_URL) as ws:
        _login_agent(ws, node_id, key)
        ws.send_json({"type": "result", "id": "nope", "ok": True})
        ws.send_json({"type": "result", "id": 5})
        ws.send_json(HEARTBEAT)
        assert ws.receive_json() == {"type": "heartbeat_ack"}
