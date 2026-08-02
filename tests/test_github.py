"""Tests for GithubAgent."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.agents.github import GithubAgent
from src.protocol.models import AgentCard, Message, Part, Task, TaskState


def _make_card() -> AgentCard:
    return AgentCard(
        name="GithubAgent",
        description="Search GitHub",
        version="1.0.0",
        skills=[],
        endpoint="http://localhost:8003",
    )


def _make_agent() -> GithubAgent:
    return GithubAgent(_make_card())


def _user_msg(text: str, **metadata) -> Message:
    return Message(role="user", parts=[Part(type="text", text=text)], metadata=metadata)


MOCK_GITHUB_RESPONSE = {
    "total_count": 2,
    "items": [
        {
            "name": "cpython",
            "description": "The Python interpreter",
            "stargazers_count": 55000,
            "html_url": "https://github.com/python/cpython",
        },
        {
            "name": "micropython",
            "description": "MicroPython",
            "stargazers_count": 17000,
            "html_url": "https://github.com/micropython/micropython",
        },
    ],
}


@pytest.mark.asyncio
async def test_handle_message_returns_results():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_GITHUB_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        msg = _user_msg("python", limit=5)
        task = Task(task_id="t1", state=TaskState.SUBMITTED)
        resp = await agent.handle_message(msg, task)

    assert resp.role == "agent"
    assert len(resp.parts) == 2
    assert "Found 2 repositories" in resp.parts[0].text
    results = resp.parts[1].data["results"]
    assert results[0]["name"] == "cpython"
    assert results[0]["stars"] == 55000
    assert results[0]["url"] == "https://github.com/python/cpython"
    assert results[1]["name"] == "micropython"


@pytest.mark.asyncio
async def test_handle_message_default_limit():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"total_count": 0, "items": []}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        msg = _user_msg("test")
        task = Task(task_id="t2", state=TaskState.SUBMITTED)
        resp = await agent.handle_message(msg, task)

    assert "Found 0 repositories" in resp.parts[0].text
    call_args = instance.get.call_args
    assert call_args[1]["params"]["per_page"] == 5
    assert call_args[1]["params"]["sort"] == "stars"


@pytest.mark.asyncio
async def test_extract_text_static():
    msg = Message(role="user", parts=[Part(type="text", text="query")])
    assert GithubAgent.extract_text(msg) == "query"

    msg2 = Message(role="user", parts=[Part(type="file", file_uri="x")])
    assert GithubAgent.extract_text(msg2) == ""
