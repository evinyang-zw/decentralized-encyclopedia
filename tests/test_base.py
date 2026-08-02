"""Tests for BaseAgent."""
from __future__ import annotations

import pytest
from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task, TaskState


class DummyAgent(BaseAgent):
    async def handle_message(self, message: Message, task: Task) -> Message:
        query = self.extract_text(message)
        return Message(role="agent", parts=[Part(type="text", text=f"echo: {query}")])


def _make_card(name: str = "Dummy") -> AgentCard:
    return AgentCard(
        name=name,
        description="Test agent",
        version="1.0.0",
        skills=[],
        endpoint="http://localhost:9999",
    )


@pytest.mark.asyncio
async def test_handle_message_returns_response():
    agent = DummyAgent(_make_card())
    msg = Message(role="user", parts=[Part(type="text", text="hello")])
    task = Task(task_id="t1", state=TaskState.SUBMITTED)
    resp = await agent.handle_message(msg, task)
    assert resp.role == "agent"
    assert resp.parts[0].text == "echo: hello"


@pytest.mark.asyncio
async def test_handle_message_empty_text():
    agent = DummyAgent(_make_card())
    msg = Message(role="user", parts=[Part(type="data", data={"k": "v"})])
    task = Task(task_id="t2", state=TaskState.SUBMITTED)
    resp = await agent.handle_message(msg, task)
    assert resp.parts[0].text == "echo: "


def test_init_sets_card_and_server():
    agent = DummyAgent(_make_card("MyAgent"), api_key="secret")
    assert agent.card.name == "MyAgent"
    assert agent.server.auth.api_key == "secret"


def test_cannot_instantiate_base_directly():
    with pytest.raises(TypeError):
        BaseAgent(_make_card())
