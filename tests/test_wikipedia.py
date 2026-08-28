"""Tests for WikipediaAgent (DBpedia Lookup API)."""
from __future__ import annotations

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


MOCK_DBPEDIA_RESPONSE = {
    "docs": [
        {
            "resource": ["http://dbpedia.org/resource/Python_(programming_language)"],
            "label": ["<B>Python</B> (programming language)"],
            "comment": ["<B>Python</B> is an interpreted, high-level programming language"],
            "refCount": ["690"],
        },
        {
            "resource": ["http://dbpedia.org/resource/Python_(genus)"],
            "label": ["Python (genus)"],
            "comment": ["Python is a genus of large constricting snakes"],
            "refCount": ["120"],
        },
    ]
}


@pytest.mark.asyncio
async def test_handle_message_returns_results():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_DBPEDIA_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        msg = _user_msg("Python")
        task = Task(task_id="t1", state=TaskState.SUBMITTED)
        resp = await agent.handle_message(msg, task)

    assert resp.role == "agent"
    assert len(resp.parts) == 2
    assert "Found 2 articles" in resp.parts[0].text
    results = resp.parts[1].data["results"]
    assert results[0]["title"] == "Python (programming language)"
    assert "interpreted" in results[0]["snippet"]
    assert "<B>" not in results[0]["title"]
    assert "<B>" not in results[0]["snippet"]


@pytest.mark.asyncio
async def test_handle_message_default_params():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"docs": []}
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

    assert "Found 0 articles" in resp.parts[0].text
    call_args = instance.get.call_args
    assert call_args[1]["params"]["maxResults"] == 5
    assert call_args[1]["params"]["query"] == "test query"


@pytest.mark.asyncio
async def test_extract_text_static():
    msg = Message(role="user", parts=[Part(type="text", text="hello")])
    assert WikipediaAgent.extract_text(msg) == "hello"

    msg2 = Message(role="user", parts=[Part(type="data", data={})])
    assert WikipediaAgent.extract_text(msg2) == ""
