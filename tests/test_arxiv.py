"""Tests for ArxivAgent with Chinese translation support."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.agents.arxiv import ArxivAgent
from src.protocol.models import AgentCard, Message, Part, Task, TaskState


def _make_card() -> AgentCard:
    return AgentCard(
        name="ArxivAgent", description="Search arXiv", version="1.0.0",
        skills=[], endpoint="http://localhost:8002",
    )


def _make_agent() -> ArxivAgent:
    return ArxivAgent(_make_card())


def _user_msg(text: str, **metadata) -> Message:
    return Message(role="user", parts=[Part(type="text", text=text)], metadata=metadata)


MOCK_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001</id>
    <title>Attention Is All You Need (revisited)</title>
    <summary>A comprehensive study of transformer architectures.</summary>
    <author><name>Vaswani</name></author>
  </entry>
</feed>"""


@pytest.mark.asyncio
async def test_handle_message_returns_results():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.text = MOCK_ARXIV_XML
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance
        resp = await agent.handle_message(_user_msg("transformer", limit=5), Task(task_id="t1", state=TaskState.SUBMITTED))
    assert resp.role == "agent"
    assert len(resp.parts) == 2
    assert "Found 1 papers" in resp.parts[0].text


@pytest.mark.asyncio
async def test_chinese_query_translated():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.text = MOCK_ARXIV_XML
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance
        resp = await agent.handle_message(_user_msg("量子计算论文"), Task(task_id="t1", state=TaskState.SUBMITTED))
    assert resp.role == "agent"
    # The translated query should contain "quantum computing"
    assert "quantum" in resp.parts[0].text.lower()


def test_parse_arxiv_response():
    results = ArxivAgent._parse_arxiv_response(MOCK_ARXIV_XML)
    assert len(results) == 1
    assert results[0]["url"] == "http://arxiv.org/abs/2301.00001"


@pytest.mark.asyncio
async def test_extract_text_static():
    msg = Message(role="user", parts=[Part(type="text", text="query")])
    assert ArxivAgent.extract_text(msg) == "query"
