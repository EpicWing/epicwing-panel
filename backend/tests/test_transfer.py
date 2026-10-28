import asyncio

import pytest

from app.services import transfer


async def _collect(generator):
    return [part async for part in generator]


def test_stream_returns_the_chunks_in_order():
    content = bytes(range(100))

    async def fetch(offset):
        # Spätere Stücke dürfen früher fertig sein, die Reihenfolge muss trotzdem stimmen.
        await asyncio.sleep(0.01 * (3 - (offset // 10) % 3))
        return content[offset : offset + 10]

    parts = asyncio.run(_collect(transfer.stream(fetch, content[:10], 100, 10, 3)))
    assert b"".join(parts) == content


def test_stream_stops_on_a_short_chunk():
    content = bytes(range(100))

    async def fetch(offset):
        return content[offset : offset + 5]

    with pytest.raises(transfer.TransferError):
        asyncio.run(_collect(transfer.stream(fetch, content[:10], 100, 10, 3)))
