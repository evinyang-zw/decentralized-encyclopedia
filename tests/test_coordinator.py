"""Tests for Coordinator Agent."""
from __future__ import annotations

import pytest

from src.agents.coordinator import Coordinator
from src.orchestrator.registry import AgentRegistry
from src.orchestrator.router import Router
from src.orchestrator.dispatcher import Dispatcher
from src.protocol.models import AgentCard, Skill, Message, Part, Task


def _setup() -> Coordinator:
    reg = AgentRegistry()
    reg.register_sync(AgentCard(
        name="WikipediaAgent", description="wiki", version="1.0.0",
        skills=[Skill(name="search_articles", description="search", input_schema={}, output_schema={})],
        endpoint="http://localhost:8001",
    ))
    router = Router(registry=reg)
    dispatcher = Dispatcher(timeout=1.0, max_retries=0)
    return Coordinator(registry=reg, router=router, dispatcher=dispatcher)


class TestCoordinator:
    def test_rule_decompose(self):
        coord = _setup()
        subtasks = coord._rule_decompose("什么是Python百科")
        assert len(subtasks) > 0
        assert subtasks[0].query == "什么是Python百科"

    def test_rule_aggregate(self):
        coord = _setup()
        results = [
            Message(role="agent", parts=[Part(type="text", text="Python is a language")]),
            Message(role="agent", parts=[Part(type="text", text="Python教程")]),
        ]
        answer = coord._rule_aggregate(results)
        assert "Python" in answer

    def test_rule_aggregate_empty(self):
        coord = _setup()
        answer = coord._rule_aggregate([])
        assert answer == "No results found."
