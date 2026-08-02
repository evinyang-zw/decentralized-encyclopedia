"""Tests for orchestrator layer."""
from __future__ import annotations

import pytest
from src.orchestrator.registry import AgentRegistry
from src.orchestrator.router import Router
from src.protocol.models import AgentCard, Skill


def _card(name: str, skills: list[str] = None) -> AgentCard:
    return AgentCard(
        name=name, description=f"{name} agent", version="1.0.0",
        skills=[Skill(name=s, description=s, input_schema={}, output_schema={}) for s in (skills or ["test"])],
        endpoint=f"http://localhost:8001",
    )


class TestRegistry:
    def test_register_and_discover(self):
        reg = AgentRegistry()
        card = _card("WikiAgent", ["search_articles"])
        reg.register_sync(card)
        found = reg.discover_sync("search_articles")
        assert len(found) == 1
        assert found[0].name == "WikiAgent"

    def test_discover_unknown_skill(self):
        reg = AgentRegistry()
        found = reg.discover_sync("nonexistent")
        assert len(found) == 0

    def test_get_all_agents(self):
        reg = AgentRegistry()
        reg.register_sync(_card("A", ["a"]))
        reg.register_sync(_card("B", ["b"]))
        assert len(reg.get_all()) == 2

    def test_unregister(self):
        reg = AgentRegistry()
        reg.register_sync(_card("A", ["a"]))
        reg.unregister_sync("A")
        assert len(reg.get_all()) == 0


class TestRouter:
    def test_keyword_match_wiki(self):
        reg = AgentRegistry()
        reg.register_sync(_card("WikipediaAgent"))
        reg.register_sync(_card("ArxivAgent"))
        router = Router(registry=reg)
        matched = router.rule_match("什么是Python百科")
        names = [c.name for c in matched]
        assert "WikipediaAgent" in names

    def test_keyword_match_arxiv(self):
        reg = AgentRegistry()
        reg.register_sync(_card("WikipediaAgent"))
        reg.register_sync(_card("ArxivAgent"))
        router = Router(registry=reg)
        matched = router.rule_match("最新的arxiv论文研究")
        names = [c.name for c in matched]
        assert "ArxivAgent" in names

    def test_no_match_returns_empty(self):
        reg = AgentRegistry()
        reg.register_sync(_card("WikipediaAgent"))
        router = Router(registry=reg)
        matched = router.rule_match("今天天气怎么样")
        assert len(matched) == 0


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch(self):
        from src.orchestrator.dispatcher import Dispatcher
        from src.protocol.models import Message, Part, Task, TaskState
        dispatcher = Dispatcher(timeout=5.0, max_retries=0)

        async def mock_send(client, msg):
            return Task(task_id="t1", state=TaskState.COMPLETED, messages=[
                Message(role="agent", parts=[Part(type="text", text="result")])
            ])

        card = _card("TestAgent")
        msg = Message(role="user", parts=[Part(type="text", text="hello")])
        results = await dispatcher.dispatch([(card, msg)], send_fn=mock_send)
        assert len(results) == 1
