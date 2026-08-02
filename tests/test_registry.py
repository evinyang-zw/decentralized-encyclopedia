"""Tests for Agent Registry."""
from __future__ import annotations

from src.orchestrator.registry import AgentRegistry
from src.protocol.models import AgentCard, Skill


def _card(name: str, skills: list[str]) -> AgentCard:
    return AgentCard(
        name=name, description=f"{name} agent", version="1.0.0",
        skills=[Skill(name=s, description=s, input_schema={}, output_schema={}) for s in skills],
        endpoint="http://localhost:8001",
    )


class TestAgentRegistry:
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

    def test_get_by_name(self):
        reg = AgentRegistry()
        reg.register_sync(_card("X", ["x"]))
        assert reg.get_by_name("X") is not None
        assert reg.get_by_name("Y") is None
