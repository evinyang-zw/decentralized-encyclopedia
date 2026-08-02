"""Tests for prompt templates."""
from __future__ import annotations

from src.llm.prompts import DECOMPOSE_PROMPT, AGGREGATE_PROMPT, ROUTE_PROMPT


class TestPrompts:
    def test_decompose_prompt_has_placeholders(self):
        result = DECOMPOSE_PROMPT.format(available_agents="Wiki, arXiv", query="test")
        assert "Wiki, arXiv" in result
        assert "test" in result

    def test_aggregate_prompt_has_placeholders(self):
        result = AGGREGATE_PROMPT.format(query="test", results="r1\nr2")
        assert "test" in result
        assert "r1\nr2" in result

    def test_route_prompt_has_placeholders(self):
        result = ROUTE_PROMPT.format(query="test", agents="Wiki, arXiv")
        assert "test" in result
