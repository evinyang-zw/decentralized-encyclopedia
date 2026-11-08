"""Tests for parallel task dispatcher."""
from __future__ import annotations

import asyncio

import pytest

from src.orchestrator.dispatcher import Dispatcher, DispatchResult
from src.protocol.models import AgentCard, Message, Part, Task, TaskState, TaskStatus


def _card(name: str = "TestAgent") -> AgentCard:
    return AgentCard(name=name, description="test", version="0.2.0", url="http://localhost:8001")


def _user_msg() -> Message:
    return Message(role="user", parts=[Part(kind="text", text="hello")])


def _completed_task(task_id: str = "t1") -> Task:
    return Task(
        id=task_id,
        status=TaskStatus(state=TaskState.COMPLETED),
        history=[Message(role="agent", parts=[Part(kind="text", text="result")])],
    )


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_returns_dispatch_result(self):
        dispatcher = Dispatcher()

        async def mock_send(client, msg):
            return _completed_task("t1")

        results = await dispatcher.dispatch([(_card(), _user_msg())], send_fn=mock_send)
        assert len(results) == 1
        assert isinstance(results[0], DispatchResult)
        assert results[0].ok is True
        assert results[0].task is not None
        assert results[0].task.id == "t1"
        assert results[0].card.name == "TestAgent"

    @pytest.mark.asyncio
    async def test_timeout_is_reported_as_failure(self):
        dispatcher = Dispatcher(timeout=0.05, max_retries=0)

        async def slow_send(client, msg):
            await asyncio.sleep(1)
            return _completed_task()

        results = await dispatcher.dispatch([(_card("SlowAgent"), _user_msg())], send_fn=slow_send)
        assert len(results) == 1
        assert results[0].ok is False
        assert results[0].error

    @pytest.mark.asyncio
    async def test_partial_failure_keeps_successful_results(self):
        dispatcher = Dispatcher(timeout=2.0, max_retries=0)

        async def send(client, msg):
            if "broken" in str(client.base_url):
                raise RuntimeError("connection refused")
            return _completed_task(f"task-{client.base_url}")

        cards = [(_card("GoodAgent"), _user_msg())]
        good = await dispatcher.dispatch(cards, send_fn=send)
        assert good[0].ok is True

        # a second card whose base_url is unreachable still yields a result object
        async def failing_send(client, msg):
            raise RuntimeError("connection refused")

        failed = await dispatcher.dispatch(
            [(_card("BrokenAgent"), _user_msg())], send_fn=failing_send
        )
        assert failed[0].ok is False
        assert "connection refused" in (failed[0].error or "")

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        dispatcher = Dispatcher(timeout=1.0, max_retries=1)
        attempts = {"n": 0}

        async def flaky_send(client, msg):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("transient")
            return _completed_task("t-retry")

        results = await dispatcher.dispatch([(_card("FlakyAgent"), _user_msg())], send_fn=flaky_send)
        assert results[0].ok is True
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_parallel_runs_concurrently(self):
        dispatcher = Dispatcher(timeout=3.0, max_retries=0)

        async def slow_send(client, msg):
            await asyncio.sleep(0.2)
            return _completed_task(client.base_url)

        cards = [(_card(f"A{i}"), _user_msg()) for i in range(5)]
        started = asyncio.get_running_loop().time()
        results = await dispatcher.dispatch(cards, send_fn=slow_send, max_concurrency=5)
        elapsed = asyncio.get_running_loop().time() - started
        assert all(r.ok for r in results)
        assert elapsed < 0.8  # 5 × 0.2s serial would be ~1.0s
