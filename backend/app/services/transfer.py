"""Streamt Daten, die der Agent stückweise liefert, als Antwort an den Browser."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable


class TransferError(Exception):
    """Ein Stück fehlt oder hat die falsche Länge, der Download ist nicht mehr zu retten."""


async def stream(
    fetch: Callable[[int], Awaitable[bytes]],
    first: bytes,
    size: int,
    chunk: int,
    window: int = 3,
) -> AsyncIterator[bytes]:
    """Gibt die Daten der Reihe nach aus, während die nächsten Stücke schon unterwegs sind.

    fetch(offset) holt das Stück ab offset, first ist das bereits gelesene erste Stück.
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
