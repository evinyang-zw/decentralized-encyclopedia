"""Tests for WikidataAgent with language-aware search."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.agents.wikidata import WikidataAgent
from src.protocol.models import AgentCard, Message, Part, Task, TaskState


def _make_card() -> AgentCard:
    return AgentCard(
        name="WikidataAgent", description="Query knowledge graph", version="1.0.0",
        skills=[], endpoint="http://localhost:8005",
    )


def _make_agent() -> WikidataAgent:
    return WikidataAgent(_make_card())


def _user_msg(text: str, **metadata) -> Message:
    return Message(role="user", parts=[Part(type="text", text=text)], metadata=metadata)


MOCK_WIKIDATA_SEARCH = {
    "search": [
        {"id": "Q937", "label": "Albert Einstein", "description": "physicist", "concepturi": "http://www.wikidata.org/entity/Q937"}
    ]
}


@pytest.mark.asyncio
async def test_handle_message_chinese_uses_zh():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"search": [{"id": "Q17995793", "label": "quantum computing", "description": "study", "concepturi": "http://www.wikidata.org/entity/Q17995793"}]}
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance
        resp = await agent.handle_message(_user_msg("量子计算"), Task(task_id="t1", state=TaskState.SUBMITTED))
    call_args = instance.get.call_args
    assert call_args[1]["params"]["language"] == "zh"
    assert resp.role == "agent"
    assert any("Found" in p.text for p in resp.parts if p.type == "text")
    data = next((p.data for p in resp.parts if p.type == "data"), None)
    assert data is not None


@pytest.mark.asyncio
async def test_handle_message_english_uses_en():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_WIKIDATA_SEARCH
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance
        await agent.handle_message(_user_msg("Einstein"), Task(task_id="t1", state=TaskState.SUBMITTED))
    call_args = instance.get.call_args
    assert call_args[1]["params"]["language"] == "en"


@pytest.mark.asyncio
async def test_handle_message_fallback():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"search": []}
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance
        resp = await agent.handle_message(_user_msg("爱因斯坦"), Task(task_id="t2", state=TaskState.SUBMITTED))
    assert "Found knowledge about Albert Einstein" in resp.parts[0].text
    assert resp.parts[1].data["type"] == "Person"


@pytest.mark.asyncio
async def test_handle_message_not_found():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"search": []}
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance
        resp = await agent.handle_message(_user_msg("NonExistentXYZ123"), Task(task_id="t3", state=TaskState.SUBMITTED))
    assert any("未找到" in p.text for p in resp.parts if p.type == "text")


def test_load_fallback_data():
    agent = _make_agent()
    assert len(agent._fallback_data) >= 2
    assert "Albert Einstein" in agent._fallback_data


def test_load_fallback_missing_file(tmp_path, monkeypatch):
    import src.agents.wikidata as wikidata_mod
    monkeypatch.setattr(wikidata_mod, "MOCK_DATA_PATH", tmp_path / "nonexistent.json")
    agent = WikidataAgent(_make_card())
    assert agent._fallback_data == {}


@pytest.mark.asyncio
async def test_extract_text_static():
    msg = Message(role="user", parts=[Part(type="text", text="query")])
    assert WikidataAgent.extract_text(msg) == "query"
