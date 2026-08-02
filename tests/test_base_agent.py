"""Tests for BaseAgent abstract class."""
from __future__ import annotations

import pytest

from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task


class TestBaseAgent:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseAgent(card=AgentCard(
                name="test", description="test", version="1.0.0",
                skills=[], endpoint="http://localhost:8001",
            ))

    def test_concrete_agent_instantiation(self):
        class MyAgent(BaseAgent):
            async def handle_message(self, message: Message, task: Task) -> Message:
                return Message(role="agent", parts=[Part(type="text", text="ok")])

        card = AgentCard(
            name="MyAgent", description="test", version="1.0.0",
            skills=[], endpoint="http://localhost:8001",
        )
        agent = MyAgent(card=card)
        assert agent.card.name == "MyAgent"
