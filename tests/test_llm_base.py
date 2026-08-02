"""Tests for LLM base module."""
from __future__ import annotations

import pytest

from src.llm.base import LLMProvider, LLMProviderError


class TestLLMProvider:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            LLMProvider()


class TestLLMProviderError:
    def test_error_message(self):
        err = LLMProviderError("test error")
        assert str(err) == "test error"
        assert isinstance(err, Exception)
