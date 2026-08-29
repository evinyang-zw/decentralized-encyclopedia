from __future__ import annotations
from typing import Any
from src.llm.base import LLMProvider, LLMProviderError

def create_llm_provider(provider_name: str, **kwargs: Any) -> LLMProvider:
    if provider_name == "openai":
        from src.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(**kwargs)
    elif provider_name == "anthropic":
        from src.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(**kwargs)
    elif provider_name == "orca":
        from src.llm.orcarouter_provider import OrcaRouterProvider
        return OrcaRouterProvider(**kwargs)
    raise LLMProviderError(f"Unknown provider: {provider_name}")
