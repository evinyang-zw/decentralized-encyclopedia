"""Tests for agent catalog + Agent Card validity.

The catalog exists because the original launch scripts published *empty* cards
(``description=''``, ``skills=[]``), which made capability discovery useless.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.agents import arxiv, github, weather, wikidata, wikipedia
from src.agents.catalog import AGENT_SPECS, build_card, get_spec
from src.protocol.server import CARD_PATH


def test_catalog_has_five_unique_agents():
    names = [spec.name for spec in AGENT_SPECS]
    assert names == [
        "WikipediaAgent",
        "ArxivAgent",
        "GithubAgent",
        "WeatherAgent",
        "WikidataAgent",
    ]
    ports = [spec.port for spec in AGENT_SPECS]
    assert len(set(names)) == len(names)
    assert len(set(ports)) == len(ports)
    assert ports == [8001, 8002, 8003, 8004, 8005]


def test_every_card_is_non_empty():
    for spec in AGENT_SPECS:
        card = build_card(spec)
        assert card.url == f"http://localhost:{spec.port}"
        assert card.description, f"{spec.name} has an empty description"
        assert card.skills, f"{spec.name} has no skills"
        for skill in card.skills:
            assert skill.id and skill.name and skill.tags


def test_get_spec_roundtrip():
    spec = get_spec("ArxivAgent")
    assert spec is not None
    assert spec.module == "src.agents.arxiv"
    assert get_spec("NoSuchAgent") is None


def test_catalog_matches_agent_classes():
    modules = {
        "WikipediaAgent": wikipedia.WikipediaAgent,
        "ArxivAgent": arxiv.ArxivAgent,
        "GithubAgent": github.GithubAgent,
        "WeatherAgent": weather.WeatherAgent,
        "WikidataAgent": wikidata.WikidataAgent,
    }
    for spec in AGENT_SPECS:
        assert modules[spec.name].__name__ == spec.class_name


@pytest.mark.asyncio
async def test_card_is_served_over_http():
    spec = get_spec("WeatherAgent")
    assert spec is not None
    agent = weather.WeatherAgent(card=build_card(spec))
    async with AsyncClient(
        transport=ASGITransport(app=agent.server.app), base_url="http://test"
    ) as http:
        resp = await http.get(CARD_PATH)
    assert resp.status_code == 200
    assert resp.json()["skills"][0]["id"] == "get-weather"
