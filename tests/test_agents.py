"""Tests for domain agents."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.agents.wikipedia import WikipediaAgent
from src.agents.arxiv import ArxivAgent
from src.agents.github import GithubAgent
from src.agents.weather import WeatherAgent
from src.agents.wikidata import WikidataAgent
from src.protocol.models import AgentCard, Skill, Message, Part, Task


def _card(name: str) -> AgentCard:
    return AgentCard(
        name=name, description=f"{name} agent", version="1.0.0",
        skills=[Skill(name="test", description="test", input_schema={}, output_schema={})],
        endpoint=f"http://localhost:8001",
    )


class TestWikipediaAgent:
    @pytest.mark.asyncio
    async def test_search(self):
        agent = WikipediaAgent(card=_card("WikipediaAgent"))
        mock_data = {
            "query": {"search": [
                {"title": "Python", "snippet": "A programming language"},
            ]}
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_data
        mock_resp.raise_for_status = MagicMock()
        with patch("src.agents.wikipedia.httpx.AsyncClient") as MockClient:
            client = MockClient.return_value
            client.get = AsyncMock(return_value=mock_resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            msg = Message(role="user", parts=[Part(type="text", text="Python")])
            result = await agent.handle_message(msg, Task(task_id="t1"))
        assert any("Python" in p.text for p in result.parts if p.type == "text")


class TestArxivAgent:
    @pytest.mark.asyncio
    async def test_search(self):
        agent = ArxivAgent(card=_card("ArxivAgent"))
        mock_xml = """<?xml version="1.0"?>
        <feed><entry>
            <title>Quantum Computing</title>
            <summary>Recent advances</summary>
            <id>http://arxiv.org/abs/2401.00001</id>
            <author><name>Alice</name></author>
        </entry></feed>"""
        mock_resp = MagicMock()
        mock_resp.text = mock_xml
        mock_resp.raise_for_status = MagicMock()
        with patch("src.agents.arxiv.httpx.AsyncClient") as MockClient:
            client = MockClient.return_value
            client.get = AsyncMock(return_value=mock_resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            msg = Message(role="user", parts=[Part(type="text", text="quantum")])
            result = await agent.handle_message(msg, Task(task_id="t1"))
        assert any("quantum" in p.text.lower() for p in result.parts if p.type == "text")


class TestGithubAgent:
    @pytest.mark.asyncio
    async def test_search(self):
        agent = GithubAgent(card=_card("GithubAgent"))
        mock_data = {"items": [{"name": "repo1", "description": "test", "stargazers_count": 10, "html_url": "http://github.com/test/repo1"}]}
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_data
        mock_resp.raise_for_status = MagicMock()
        with patch("src.agents.github.httpx.AsyncClient") as MockClient:
            client = MockClient.return_value
            client.get = AsyncMock(return_value=mock_resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            msg = Message(role="user", parts=[Part(type="text", text="test")])
            result = await agent.handle_message(msg, Task(task_id="t1"))
        assert any("Found" in p.text for p in result.parts if p.type == "text")


class TestWeatherAgent:
    @pytest.mark.asyncio
    async def test_weather(self):
        agent = WeatherAgent(card=_card("WeatherAgent"))
        mock_data = {
            "current_condition": [{"temp_C": "25", "humidity": "60", "weatherDesc": [{"value": "clear sky"}]}],
            "nearest_area": [{"areaName": [{"value": "Beijing"}], "country": [{"value": "China"}]}],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_data
        mock_resp.raise_for_status = MagicMock()
        with patch("src.agents.weather.httpx.AsyncClient") as MockClient:
            client = MockClient.return_value
            client.get = AsyncMock(return_value=mock_resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            msg = Message(role="user", parts=[Part(type="text", text="Beijing")])
            result = await agent.handle_message(msg, Task(task_id="t1"))
        assert any("25" in p.text for p in result.parts if p.type == "text")


class TestWikidataAgent:
    @pytest.mark.asyncio
    async def test_query_found(self):
        agent = WikidataAgent(card=_card("WikidataAgent"))
        msg = Message(role="user", parts=[Part(type="text", text="Einstein")])
        result = await agent.handle_message(msg, Task(task_id="t1"))
        assert any("Einstein" in p.text for p in result.parts if p.type == "text")

    @pytest.mark.asyncio
    async def test_query_not_found(self):
        agent = WikidataAgent(card=_card("WikidataAgent"))
        msg = Message(role="user", parts=[Part(type="text", text="NonExistentXYZ")])
        result = await agent.handle_message(msg, Task(task_id="t1"))
        assert any("未找到" in p.text for p in result.parts if p.type == "text")
