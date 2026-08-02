from __future__ import annotations
from abc import ABC, abstractmethod

class LLMProviderError(Exception):
    pass

class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs) -> str:
        ...
