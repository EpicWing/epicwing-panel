"""Der Konsolen-Watch bleibt, solange das Panel auf die Bereitmeldung wartet."""

import asyncio
import uuid

from app.agentlink.console import ConsoleHub
from app.agentlink.protocol import CommandResult
from app.services.startup_ready import watcher


class FakeCommands:
    def __init__(self):
        self.actions = []

    async def send(self, node_id, action, params, timeout=90):
        self.actions.append(action)
        return CommandResult(type="result", id="x", ok=True, data={})


def test_unsubscribe_keeps_watch_while_waiting_for_ready():
    commands = FakeCommands()
    hub = ConsoleHub(commands)
    node, ws = uuid.uuid4(), object()

    async def run():
        await hub.subscribe("n", node, ws)
        await hub.unsubscribe("n", ws)

    watcher.watch("n", ("x",), 0.0)
    try:
        asyncio.run(run())
    finally:
        watcher.forget("n")
    assert commands.actions == ["console.watch"]


def test_unsubscribe_unwatches_without_pending_ready():
    commands = FakeCommands()
    hub = ConsoleHub(commands)
    node, ws = uuid.uuid4(), object()

    async def run():
        await hub.subscribe("n", node, ws)
        await hub.unsubscribe("n", ws)

    asyncio.run(run())
    assert commands.actions == ["console.watch", "console.unwatch"]


def test_release_only_without_viewers():
    commands = FakeCommands()
    hub = ConsoleHub(commands)
    node, ws = uuid.uuid4(), object()

    async def run():
        await hub.release(node, "n")
        await hub.subscribe("n", node, ws)
        await hub.release(node, "n")
        await hub.ensure_watch(node, "n")

    asyncio.run(run())
    assert commands.actions == ["console.unwatch", "console.watch", "console.watch"]
