"""SSE streaming support for A2A protocol."""
from __future__ import annotations
import asyncio
import json
from typing import AsyncIterator

DONE_MARKER = "data: [DONE]\n\n"


def format_sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


class EventEmitter:
    def __init__(self):
        self._queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def emit(self, event: dict) -> None:
        await self._queue.put(event)

    async def done(self) -> None:
        await self._queue.put(None)

    async def stream(self) -> AsyncIterator[dict]:
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event
