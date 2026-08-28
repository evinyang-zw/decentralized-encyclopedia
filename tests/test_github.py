"""Tests for GithubAgent with Chinese translation support."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.agents.github import GithubAgent
from src.protocol.models import AgentCard, Message, Part, Task, TaskState


def _make_card() -> AgentCard:
    return AgentCard(
        name="GithubAgent", description="Search GitLab", version="1.0.0",
        skills=[], endpoint="http://localhost:8003",
    )


def _make_agent() -> GithubAgent:
    return GithubAgent(_make_card())


def _user_msg(text: str, **metadata) -> Message:
    return Message(role="user", parts=[Part(type="text", text=text)], metadata=metadata)


MOCK_GITLAB_RESPONSE = [
    {"name": "ase", "description": "A Python library", "star_count": 516, "web_url": "https://gitlab.com/ase/ase"},
    {"name": "mlreef", "description": "ML management", "star_count": 79, "web_url": "https://gitlab.com/mlreef/mlreef"},
]


@pytest.mark.asyncio
async def test_handle_message_returns_results():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_GITLAB_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance
        resp = await agent.handle_message(_user_msg("python", limit=5), Task(task_id="t1", state=TaskState.SUBMITTED))
    assert resp.role == "agent"
    assert "Found 2 repositories" in resp.parts[0].text
    results = resp.parts[1].data["results"]
    assert results[0]["name"] == "ase"
    assert results[0]["stars"] == 516


@pytest.mark.asyncio
async def test_chinese_query_translated():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_GITLAB_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance
        resp = await agent.handle_message(_user_msg("开源机器学习项目"), Task(task_id="t1", state=TaskState.SUBMITTED))
    assert resp.role == "agent"
    assert "Found" in resp.parts[0].text


@pytest.mark.asyncio
async def test_handle_message_empty():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance
        resp = await agent.handle_message(_user_msg("nonexistent"), Task(task_id="t2", state=TaskState.SUBMITTED))
    assert "Found 0 repositories" in resp.parts[0].text


@pytest.mark.asyncio
async def test_extract_text_static():
    msg = Message(role="user", parts=[Part(type="text", text="query")])
    assert GithubAgent.extract_text(msg) == "query"
