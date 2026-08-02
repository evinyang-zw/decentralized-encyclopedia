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


def _make_agent(api_key: str | None = None, weather_api_key: str | None = "test-weather-key") -> WeatherAgent:
    return WeatherAgent(_make_card(), api_key=api_key, weather_api_key=weather_api_key)


def _user_msg(text: str, **metadata) -> Message:
    return Message(role="user", parts=[Part(type="text", text=text)], metadata=metadata)


MOCK_WEATHER_RESPONSE = {
    "name": "Beijing",
    "main": {"temp": 28.5, "humidity": 65},
    "weather": [{"description": "scattered clouds"}],
}


@pytest.mark.asyncio
async def test_handle_message_returns_weather():
    agent = _make_agent()
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_WEATHER_RESPONSE
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
    assert "28.5" in resp.parts[0].text
    assert "scattered clouds" in resp.parts[0].text
    data = resp.parts[1].data
    assert data["city"] == "Beijing"
    assert data["temperature"] == 28.5
    assert data["humidity"] == 65
    assert data["condition"] == "scattered clouds"


@pytest.mark.asyncio
async def test_handle_message_no_weather_key():
    agent = _make_agent(weather_api_key=None)
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_WEATHER_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = instance

        msg = _user_msg("Beijing")
        task = Task(task_id="t2", state=TaskState.SUBMITTED)
        await agent.handle_message(msg, task)

    # Verify empty API key is sent
    call_args = instance.get.call_args
    assert call_args[1]["params"]["appid"] == ""
    assert call_args[1]["params"]["units"] == "metric"


def test_init_stores_weather_api_key():
    agent = _make_agent(weather_api_key="my-weather-key")
    assert agent.weather_api_key == "my-weather-key"
    # A2A server api_key is separate (not passed)
    assert agent.server.auth.api_key is None


@pytest.mark.asyncio
async def test_extract_text_static():
    msg = Message(role="user", parts=[Part(type="text", text="London")])
    assert WeatherAgent.extract_text(msg) == "London"

    msg2 = Message(role="user", parts=[])
    assert WeatherAgent.extract_text(msg2) == ""
