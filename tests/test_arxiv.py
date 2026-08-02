"""Tests for ArxivAgent."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.agents.arxiv import ArxivAgent
from src.protocol.models import AgentCard, Message, Part, Task, TaskState


def _make_card() -> AgentCard:
    return AgentCard(
        name="ArxivAgent",
        description="Search arXiv",
        version="1.0.0",
        skills=[],
        endpoint="http://localhost:8002",
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
    <author><name>Shazeer</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2301.00002</id>
    <title>BERT: Pre-training of Deep Bidirectional Transformers</title>
    <summary>We introduce BERT, a new language representation model.</summary>
    <author><name>Devlin</name></author>
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

        msg = _user_msg("transformer", limit=5)
        task = Task(task_id="t1", state=TaskState.SUBMITTED)
        resp = await agent.handle_message(msg, task)

    assert resp.role == "agent"
    assert len(resp.parts) == 2
    assert "Found 2 papers" in resp.parts[0].text
    results = resp.parts[1].data["results"]
    assert len(results) == 2
    assert results[0]["title"] == "Attention Is All You Need (revisited)"
    assert "Vaswani" in results[0]["authors"]
    assert results[1]["title"] == "BERT: Pre-training of Deep Bidirectional Transformers"


@pytest.mark.asyncio
async def test_handle_message_empty_results():
    agent = _make_agent()
    empty_xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>"""
    mock_resp = MagicMock()
    mock_resp.text = empty_xml
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        msg = _user_msg("nonexistent topic")
        task = Task(task_id="t2", state=TaskState.SUBMITTED)
        resp = await agent.handle_message(msg, task)

    assert "Found 0 papers" in resp.parts[0].text


def test_parse_arxiv_response():
    results = ArxivAgent._parse_arxiv_response(MOCK_ARXIV_XML)
    assert len(results) == 2
    assert results[0]["url"] == "http://arxiv.org/abs/2301.00001"
    assert len(results[0]["authors"]) == 2
    assert "transformer" in results[0]["abstract"].lower()


def test_parse_arxiv_response_malformed():
    results = ArxivAgent._parse_arxiv_response("<not-valid-xml/>")
    # ET.fromstring raises on malformed, but a simple root without entries returns empty
    assert results == []


@pytest.mark.asyncio
async def test_extract_text_static():
    msg = Message(role="user", parts=[Part(type="text", text="query")])
    assert ArxivAgent.extract_text(msg) == "query"

    msg2 = Message(role="user", parts=[])
    assert ArxivAgent.extract_text(msg2) == ""
