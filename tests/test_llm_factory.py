"""Tests for LLM provider factory."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from src.llm.factory import create_llm_provider
from src.llm.base import LLMProviderError


class TestCreateLLMProvider:
    def test_create_openai(self):
        with patch("src.llm.openai_provider.AsyncOpenAI"):
            p = create_llm_provider("openai", api_key="test")
            assert p._model == "gpt-4o"

    def test_create_anthropic(self):
        with patch("src.llm.anthropic_provider.AsyncAnthropic"):
            p = create_llm_provider("anthropic", api_key="test")
            assert p._model == "claude-sonnet-4-20250514"

    def test_unknown_provider(self):
        with pytest.raises(LLMProviderError):
            create_llm_provider("unknown", api_key="test")
