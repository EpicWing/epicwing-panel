"""Streams data that the agent delivers in pieces as the response to the browser."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable


class TransferError(Exception):
    """A chunk is missing or has the wrong length, the download cannot be saved."""


async def stream(
    fetch: Callable[[int], Awaitable[bytes]],
    first: bytes,
    size: int,
    chunk: int,
    window: int = 3,
) -> AsyncIterator[bytes]:
    """Yields the data in order while the next chunks are already on the way.

    fetch(offset) gets the chunk from offset, first is the first chunk that was already read.
    """
    if first:
        yield first
    sent = requested = len(first)
    pending: deque[asyncio.Task[bytes]] = deque()
    try:
        while sent < size:
            while requested < size and len(pending) < window:
                pending.append(asyncio.create_task(fetch(requested)))
                requested += min(chunk, size - requested)
            data = await pending.popleft()
            if len(data) != min(chunk, size - sent):
                raise TransferError("incomplete chunk")
            yield data
            sent += len(data)
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
