from __future__ import annotations
from openai import AsyncOpenAI
from src.llm.base import LLMProvider, LLMProviderError

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def chat(self, messages: list[dict], **kwargs) -> str:
        try:
            resp = await self._client.chat.completions.create(model=self._model, messages=messages)
            return resp.choices[0].message.content or ""
        except Exception as e:
            raise LLMProviderError(f"OpenAI error: {e}") from e
