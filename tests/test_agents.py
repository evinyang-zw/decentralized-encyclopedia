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
            "docs": [{
                "resource": ["http://dbpedia.org/resource/Python_(programming_language)"],
                "label": ["Python (programming language)"],
                "comment": ["Python is an interpreted programming language"],
            }]
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

    @pytest.mark.asyncio
    async def test_chinese_query_translated(self):
        agent = ArxivAgent(card=_card("ArxivAgent"))
        mock_xml = """<?xml version="1.0"?><feed><entry>
            <title>Quantum Computing Survey</title><summary>A survey</summary>
            <id>http://arxiv.org/abs/1</id><author><name>A</name></author>
        </entry></feed>"""
        mock_resp = MagicMock()
        mock_resp.text = mock_xml
        mock_resp.raise_for_status = MagicMock()
        with patch("src.agents.arxiv.httpx.AsyncClient") as MockClient:
            client = MockClient.return_value
            client.get = AsyncMock(return_value=mock_resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            msg = Message(role="user", parts=[Part(type="text", text="量子计算论文")])
            result = await agent.handle_message(msg, Task(task_id="t1"))
        assert any("paper" in p.text.lower() or "quantum" in p.text.lower() for p in result.parts if p.type == "text")


class TestGithubAgent:
    @pytest.mark.asyncio
    async def test_search(self):
        agent = GithubAgent(card=_card("GithubAgent"))
        mock_data = [{"name": "repo1", "description": "test project", "star_count": 100, "web_url": "https://gitlab.com/user/repo1"}]
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

    @pytest.mark.asyncio
    async def test_chinese_query_translated(self):
        agent = GithubAgent(card=_card("GithubAgent"))
        mock_data = [{"name": "ml-project", "description": "ML", "star_count": 50, "web_url": "https://gitlab.com/x/ml"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_data
        mock_resp.raise_for_status = MagicMock()
        with patch("src.agents.github.httpx.AsyncClient") as MockClient:
            client = MockClient.return_value
            client.get = AsyncMock(return_value=mock_resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            msg = Message(role="user", parts=[Part(type="text", text="开源机器学习项目")])
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
    async def test_query_api_chinese(self):
        agent = WikidataAgent(card=_card("WikidataAgent"))
        mock_api_data = {
            "search": [
                {"id": "Q17995793", "label": "quantum computing", "description": "study of computation", "concepturi": "http://www.wikidata.org/entity/Q17995793"}
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_api_data
        mock_resp.raise_for_status = MagicMock()
        with patch("src.agents.wikidata.httpx.AsyncClient") as MockClient:
            client = MockClient.return_value
            client.get = AsyncMock(return_value=mock_resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            msg = Message(role="user", parts=[Part(type="text", text="量子计算")])
            result = await agent.handle_message(msg, Task(task_id="t1"))
        # Verify language=zh was used
        call_args = client.get.call_args
        assert call_args[1]["params"]["language"] == "zh"
        assert any("Found" in p.text for p in result.parts if p.type == "text")
        data = next((p.data for p in result.parts if p.type == "data"), None)
        assert data is not None

    @pytest.mark.asyncio
    async def test_query_api_english(self):
        agent = WikidataAgent(card=_card("WikidataAgent"))
        mock_api_data = {
            "search": [
                {"id": "Q937", "label": "Albert Einstein", "description": "physicist", "concepturi": "http://www.wikidata.org/entity/Q937"}
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_api_data
        mock_resp.raise_for_status = MagicMock()
        with patch("src.agents.wikidata.httpx.AsyncClient") as MockClient:
            client = MockClient.return_value
            client.get = AsyncMock(return_value=mock_resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            msg = Message(role="user", parts=[Part(type="text", text="Einstein")])
            result = await agent.handle_message(msg, Task(task_id="t1"))
        call_args = client.get.call_args
        assert call_args[1]["params"]["language"] == "en"

    @pytest.mark.asyncio
    async def test_query_fallback(self):
        agent = WikidataAgent(card=_card("WikidataAgent"))
        mock_empty = {"search": []}
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_empty
        mock_resp.raise_for_status = MagicMock()
        with patch("src.agents.wikidata.httpx.AsyncClient") as MockClient:
            client = MockClient.return_value
            client.get = AsyncMock(return_value=mock_resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            msg = Message(role="user", parts=[Part(type="text", text="爱因斯坦")])
            result = await agent.handle_message(msg, Task(task_id="t1"))
        assert any("Einstein" in p.text for p in result.parts if p.type == "text")

    @pytest.mark.asyncio
    async def test_query_not_found(self):
        agent = WikidataAgent(card=_card("WikidataAgent"))
        mock_empty = {"search": []}
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_empty
        mock_resp.raise_for_status = MagicMock()
        with patch("src.agents.wikidata.httpx.AsyncClient") as MockClient:
            client = MockClient.return_value
            client.get = AsyncMock(return_value=mock_resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            msg = Message(role="user", parts=[Part(type="text", text="NonExistentXYZ123")])
            result = await agent.handle_message(msg, Task(task_id="t1"))
        assert any("未找到" in p.text for p in result.parts if p.type == "text")
