"""OrcaRouter — OpenAI-compatible API gateway with automatic model fallback."""
from __future__ import annotations

from openai import AsyncOpenAI

from src.llm.base import LLMProvider, LLMProviderError


class OrcaRouterProvider(LLMProvider):
    BASE_URL = "https://api.orcarouter.ai/v1"
    DEFAULT_MODEL = "orcarouter/free"
    FALLBACK_MODELS = [
        "deepseek/deepseek-v4-flash-free",
        "tencent/hy3-free",
        "qwen/qwen3.8-27b-free",
    ]

    def __init__(self, api_key: str, model: str | None = None):
        self._client = AsyncOpenAI(base_url=self.BASE_URL, api_key=api_key)
        self._model = model or self.DEFAULT_MODEL
        self._fallback_models = [m for m in self.FALLBACK_MODELS if m != self._model]

    async def chat(self, messages: list[dict], **kwargs) -> str:
        models_to_try = [self._model] + self._fallback_models
        last_error = None
        for model in models_to_try:
            try:
                resp = await self._client.chat.completions.create(
                    model=model, messages=messages, **kwargs,
                )
                return resp.choices[0].message.content or ""
            except Exception as e:
                last_error = e
                continue
        raise LLMProviderError(f"All OrcaRouter models failed: {last_error}")
