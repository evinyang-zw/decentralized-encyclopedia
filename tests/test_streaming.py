"""Tests for SSE streaming support."""
from __future__ import annotations

import json

import pytest

from src.protocol.streaming import EventEmitter, format_sse, DONE_MARKER


class TestFormatSse:
    def test_format_sse(self):
        event = {"type": "message", "data": "hello"}
        result = format_sse(event)
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        parsed = json.loads(result.removeprefix("data: ").removesuffix("\n\n"))
        assert parsed["type"] == "message"

    def test_done_marker(self):
        assert DONE_MARKER == "data: [DONE]\n\n"


class TestEventEmitter:
    @pytest.mark.asyncio
    async def test_emit_and_receive(self):
        emitter = EventEmitter()
        await emitter.emit({"type": "msg", "text": "hello"})
        await emitter.done()
        events = []
        async for event in emitter.stream():
            events.append(event)
        assert len(events) == 1
        assert events[0]["text"] == "hello"

    @pytest.mark.asyncio
    async def test_multiple_events(self):
        emitter = EventEmitter()
        for i in range(3):
            await emitter.emit({"i": i})
        await emitter.done()
        events = []
        async for event in emitter.stream():
            events.append(event)
        assert len(events) == 3
