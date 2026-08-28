"""Tests for WeatherAgent."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.agents.weather import WeatherAgent
from src.protocol.models import AgentCard, Message, Part, Task, TaskState


def _make_card() -> AgentCard:
    return AgentCard(
        name="WeatherAgent",
        description="Get weather",
        version="1.0.0",
        skills=[],
        endpoint="http://localhost:8004",
    )


def _make_agent() -> WeatherAgent:
    return WeatherAgent(_make_card())


def _user_msg(text: str, **metadata) -> Message:
    return Message(role="user", parts=[Part(type="text", text=text)], metadata=metadata)


MOCK_WTTR_RESPONSE = {
    "current_condition": [{
        "temp_C": "28",
        "humidity": "65",
        "weatherDesc": [{"value": "Scattered clouds"}],
    }],
    "nearest_area": [{
        "areaName": [{"value": "Beijing"}],
        "country": [{"value": "China"}],
    }],
}


@pytest.mark.asyncio
async def test_handle_message_returns_weather():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_WTTR_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        msg = _user_msg("Beijing")
        task = Task(task_id="t1", state=TaskState.SUBMITTED)
        resp = await agent.handle_message(msg, task)

    assert resp.role == "agent"
    assert len(resp.parts) == 2
    assert "Beijing" in resp.parts[0].text
    assert "28" in resp.parts[0].text
    assert "Scattered clouds" in resp.parts[0].text
    data = resp.parts[1].data
    assert data["city"] == "Beijing"
    assert data["temperature"] == 28
    assert data["humidity"] == 65
    assert data["condition"] == "Scattered clouds"


@pytest.mark.asyncio
async def test_handle_message_calls_correct_url():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_WTTR_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        msg = _user_msg("Tokyo")
        task = Task(task_id="t2", state=TaskState.SUBMITTED)
        await agent.handle_message(msg, task)

    call_args = instance.get.call_args
    assert "wttr.in/Tokyo?format=j1" in call_args[0][0]


@pytest.mark.asyncio
async def test_extract_text_static():
    msg = Message(role="user", parts=[Part(type="text", text="London")])
    assert WeatherAgent.extract_text(msg) == "London"

    msg2 = Message(role="user", parts=[])
    assert WeatherAgent.extract_text(msg2) == ""
