"""Tests for parallel task dispatcher."""
from __future__ import annotations

import asyncio

import pytest

from src.orchestrator.dispatcher import Dispatcher
from src.protocol.models import AgentCard, Message, Part, Task, TaskState


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_parallel(self):
        dispatcher = Dispatcher()

        async def mock_send(client, msg):
            return Task(task_id="t1", state=TaskState.COMPLETED, messages=[
                Message(role="agent", parts=[Part(type="text", text="result")])
            ])

        card = AgentCard(
            name="TestAgent", description="test", version="1.0.0",
            skills=[], endpoint="http://localhost:8001",
        )
        msg = Message(role="user", parts=[Part(type="text", text="hello")])
        results = await dispatcher.dispatch([(card, msg)], send_fn=mock_send)
        assert len(results) == 1
        assert results[0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_dispatch_with_timeout(self):
        dispatcher = Dispatcher(timeout=0.1)

        async def slow_send(client, msg):
            await asyncio.sleep(1)
            return Task(task_id="t1", state=TaskState.COMPLETED)

        card = AgentCard(
            name="SlowAgent", description="slow", version="1.0.0",
            skills=[], endpoint="http://localhost:8001",
        )
        msg = Message(role="user", parts=[Part(type="text", text="hello")])
        results = await dispatcher.dispatch([(card, msg)], send_fn=slow_send)
        assert len(results) == 0
