"""BaseAgent — abstract base class for all domain agents."""
from __future__ import annotations
from abc import ABC, abstractmethod

from src.protocol.models import AgentCard, Message, Part, Task
from src.protocol.server import A2AServer


class BaseAgent(ABC):
    def __init__(self, card: AgentCard, api_key: str | None = None):
        self.card = card
        self.server = A2AServer(card, api_key)

    @abstractmethod
    async def handle_message(self, message: Message, task: Task) -> Message:
        ...

    @staticmethod
    def extract_text(message: Message) -> str:
        for part in message.parts:
            if part.type == "text" and part.text:
                return part.text
        return ""

    def start(self, port: int):
        self.server.handle_message = self.handle_message
        self.server.start(port=port)
