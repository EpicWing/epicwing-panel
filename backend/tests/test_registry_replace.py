import asyncio
import uuid

from app.agentlink.protocol import WS_REPLACED, WS_REPLACED_REASON
from app.agentlink.registry import AgentRegistry


class FakeSocket:
    def __init__(self):
        self.closed = None

    async def close(self, code=1000, reason=None):
        self.closed = (code, reason)


def test_replaced_connection_is_closed_with_the_reason():
    registry = AgentRegistry()
    node_id = uuid.uuid4()
    old, new = FakeSocket(), FakeSocket()
    asyncio.run(registry.register(node_id, old))
    asyncio.run(registry.register(node_id, new))
    assert old.closed == (WS_REPLACED, WS_REPLACED_REASON)
    assert new.closed is None
    assert registry.connection(node_id) is new
