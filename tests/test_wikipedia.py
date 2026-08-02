"""Tests for WikipediaAgent."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.agents.wikipedia import WikipediaAgent
from src.protocol.models import AgentCard, Message, Part, Task, TaskState


def _make_card() -> AgentCard:
    return AgentCard(
        name="WikipediaAgent",
        description="Search Wikipedia",
        version="1.0.0",
        skills=[],
        endpoint="http://localhost:8001",
    )


def _make_agent() -> WikipediaAgent:
    return WikipediaAgent(_make_card())


def _user_msg(text: str, **metadata) -> Message:
    return Message(role="user", parts=[Part(type="text", text=text)], metadata=metadata)


MOCK_SEARCH_RESPONSE = {
    "query": {
        "search": [
            {"title": "Python (programming language)", "snippet": "Python is a programming language"},
            {"title": "Python (genus)", "snippet": "Python is a genus of snakes"},
        ]
    }
}


@pytest.mark.asyncio
async def test_handle_message_returns_results():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_SEARCH_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        msg = _user_msg("Python", lang="en", limit=5)
        task = Task(task_id="t1", state=TaskState.SUBMITTED)
        resp = await agent.handle_message(msg, task)

    assert resp.role == "agent"
    assert len(resp.parts) == 2
    assert "Found 2 Wikipedia articles" in resp.parts[0].text
    assert resp.parts[1].data["results"][0]["title"] == "Python (programming language)"


@pytest.mark.asyncio
async def test_handle_message_default_params():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"query": {"search": []}}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        msg = _user_msg("test query")
        task = Task(task_id="t2", state=TaskState.SUBMITTED)
        resp = await agent.handle_message(msg, task)

    assert "Found 0 Wikipedia articles" in resp.parts[0].text
    # Verify default params
    call_args = instance.get.call_args
    assert call_args[1]["params"]["srlimit"] == 5
    assert call_args[1]["params"]["srsearch"] == "test query"


@pytest.mark.asyncio
async def test_extract_text_static():
    msg = Message(role="user", parts=[Part(type="text", text="hello")])
    assert WikipediaAgent.extract_text(msg) == "hello"

    msg2 = Message(role="user", parts=[Part(type="data", data={})])
    assert WikipediaAgent.extract_text(msg2) == ""
