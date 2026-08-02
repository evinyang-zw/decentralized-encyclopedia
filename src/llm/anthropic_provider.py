from __future__ import annotations
from typing import Any
from anthropic import AsyncAnthropic
from src.llm.base import LLMProvider, LLMProviderError

class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def chat(self, messages: list[dict], **kwargs) -> str:
        system_msg = ""
        anthropic_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg.get("content", "")
            else:
                anthropic_messages.append(msg)
        try:
            params: dict[str, Any] = {"model": self._model, "max_tokens": 4096, "messages": anthropic_messages}
            if system_msg:
                params["system"] = system_msg
            resp = await self._client.messages.create(**params)
            return "".join(b.text for b in resp.content if b.type == "text")
        except Exception as e:
            raise LLMProviderError(f"Anthropic error: {e}") from e
