"""Tests for WikidataAgent."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from src.agents.wikidata import WikidataAgent
from src.protocol.models import AgentCard, Message, Part, Task, TaskState


def _make_card() -> AgentCard:
    return AgentCard(
        name="WikidataAgent",
        description="Query knowledge graph",
        version="1.0.0",
        skills=[],
        endpoint="http://localhost:8005",
    )


def _make_agent() -> WikidataAgent:
    return WikidataAgent(_make_card())


def _user_msg(text: str, **metadata) -> Message:
    return Message(role="user", parts=[Part(type="text", text=text)], metadata=metadata)


@pytest.mark.asyncio
async def test_handle_message_found():
    agent = _make_agent()
    msg = _user_msg("Albert Einstein")
    task = Task(task_id="t1", state=TaskState.SUBMITTED)
    resp = await agent.handle_message(msg, task)

    assert resp.role == "agent"
    assert len(resp.parts) == 2
    assert "Found knowledge about Albert Einstein" in resp.parts[0].text
    data = resp.parts[1].data
    assert data["type"] == "Person"
    assert data["birth"] == "1879-03-14"
    assert "Theory of Relativity" in data["known_for"]


@pytest.mark.asyncio
async def test_handle_message_case_insensitive():
    agent = _make_agent()
    msg = _user_msg("python")
    task = Task(task_id="t2", state=TaskState.SUBMITTED)
    resp = await agent.handle_message(msg, task)

    assert "Found knowledge about Python (programming language)" in resp.parts[0].text
    assert resp.parts[1].data["creator"] == "Guido van Rossum"


@pytest.mark.asyncio
async def test_handle_message_partial_match():
    agent = _make_agent()
    msg = _user_msg("Einstein")
    task = Task(task_id="t3", state=TaskState.SUBMITTED)
    resp = await agent.handle_message(msg, task)

    assert "Found knowledge about Albert Einstein" in resp.parts[0].text


@pytest.mark.asyncio
async def test_handle_message_not_found():
    agent = _make_agent()
    msg = _user_msg("Quantum entanglement")
    task = Task(task_id="t4", state=TaskState.SUBMITTED)
    resp = await agent.handle_message(msg, task)

    assert len(resp.parts) == 1
    assert "未找到" in resp.parts[0].text
    assert "quantum entanglement" in resp.parts[0].text


def test_load_mock_data():
    agent = _make_agent()
    assert len(agent._data) >= 2
    assert "Albert Einstein" in agent._data
    assert "Python (programming language)" in agent._data


def test_load_mock_data_missing_file(tmp_path, monkeypatch):
    import src.agents.wikidata as wikidata_mod
    monkeypatch.setattr(wikidata_mod, "MOCK_DATA_PATH", tmp_path / "nonexistent.json")
    card = _make_card()
    agent = WikidataAgent(card)
    assert agent._data == {}


@pytest.mark.asyncio
async def test_extract_text_static():
    msg = Message(role="user", parts=[Part(type="text", text="query")])
    assert WikidataAgent.extract_text(msg) == "query"

    msg2 = Message(role="user", parts=[Part(type="data", data={})])
    assert WikidataAgent.extract_text(msg2) == ""
