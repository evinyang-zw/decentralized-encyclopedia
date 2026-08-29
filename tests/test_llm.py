"""Tests for LLM layer."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from src.llm.base import LLMProvider, LLMProviderError
from src.llm.factory import create_llm_provider
from src.llm.prompts import DECOMPOSE_PROMPT, AGGREGATE_PROMPT, ROUTE_PROMPT


class TestLLMProvider:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            LLMProvider()

    def test_error_message(self):
        err = LLMProviderError("test error")
        assert str(err) == "test error"


class TestFactory:
    def test_create_openai(self):
        with patch("src.llm.openai_provider.AsyncOpenAI"):
            p = create_llm_provider("openai", api_key="test")
            assert p._model == "gpt-4o"

    def test_create_anthropic(self):
        with patch("src.llm.anthropic_provider.AsyncAnthropic"):
            p = create_llm_provider("anthropic", api_key="test")
            assert p._model == "claude-sonnet-4-20250514"

    def test_create_orca(self):
        with patch("src.llm.orcarouter_provider.AsyncOpenAI"):
            p = create_llm_provider("orca", api_key="sk-orca-test")
            assert p._model == "orcarouter/free"

    def test_create_orca_custom_model(self):
        with patch("src.llm.orcarouter_provider.AsyncOpenAI"):
            p = create_llm_provider("orca", api_key="sk-orca-test", model="qwen/qwen3.6-plus")
            assert p._model == "qwen/qwen3.6-plus"

    def test_unknown_provider(self):
        with pytest.raises(LLMProviderError):
            create_llm_provider("unknown", api_key="test")


class TestPrompts:
    def test_decompose_prompt(self):
        result = DECOMPOSE_PROMPT.format(available_agents="Wiki, arXiv", query="test")
        assert "Wiki, arXiv" in result
        assert "test" in result

    def test_aggregate_prompt(self):
        result = AGGREGATE_PROMPT.format(query="test", results="r1\nr2")
        assert "test" in result

    def test_route_prompt(self):
        result = ROUTE_PROMPT.format(query="test", agents="Wiki, arXiv")
        assert "test" in result
