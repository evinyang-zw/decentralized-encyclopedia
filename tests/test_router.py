"""Tests for Router."""
from __future__ import annotations

import pytest

from src.orchestrator.router import Router
from src.orchestrator.registry import AgentRegistry
from src.protocol.models import AgentCard, Skill


def _setup_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register_sync(AgentCard(
        name="WikipediaAgent", description="wiki", version="1.0.0",
        skills=[Skill(name="search_articles", description="search", input_schema={}, output_schema={})],
        endpoint="http://localhost:8001",
    ))
    reg.register_sync(AgentCard(
        name="ArxivAgent", description="arxiv", version="1.0.0",
        skills=[Skill(name="search_papers", description="search", input_schema={}, output_schema={})],
        endpoint="http://localhost:8002",
    ))
    return reg


class TestRouter:
    def test_keyword_match_wiki(self):
        router = Router(registry=_setup_registry())
        matched = router.rule_match("什么是Python百科")
        names = [c.name for c in matched]
        assert "WikipediaAgent" in names

    def test_keyword_match_arxiv(self):
        router = Router(registry=_setup_registry())
        matched = router.rule_match("最新的arxiv论文研究")
        names = [c.name for c in matched]
        assert "ArxivAgent" in names

    def test_no_match_returns_empty(self):
        router = Router(registry=_setup_registry())
        matched = router.rule_match("今天天气怎么样")
        assert len(matched) == 0
