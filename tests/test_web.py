"""Tests for Web layer."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from src.web.app import create_app
from src.web.api import init_coordinator
from src.orchestrator.registry import AgentRegistry


class TestWebApp:
    @pytest.mark.asyncio
    async def test_health(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_agent_status(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/agents")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestQueryEndpoint:
    @pytest.mark.asyncio
    async def test_query_coordinator_not_initialized(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/query", json={"question": "test"})
        assert resp.status_code == 503
        assert "not initialized" in resp.json()["error"].lower()

    @pytest.mark.asyncio
    async def test_query_empty_question(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/query", json={"question": ""})
        assert resp.status_code == 400
        assert "missing" in resp.json()["error"].lower()

    @pytest.mark.asyncio
    async def test_query_no_question_field(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/query", json={})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_query_too_long(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/query", json={"question": "x" * 5000})
        assert resp.status_code == 400
        assert "too long" in resp.json()["error"].lower()

    @pytest.mark.asyncio
    async def test_query_valid_with_coordinator(self):
        from src.agents.coordinator import Coordinator
        from src.orchestrator.router import Router
        from src.orchestrator.dispatcher import Dispatcher
        from src.protocol.models import AgentCard, Skill

        reg = AgentRegistry()
        reg.register_sync(AgentCard(
            name="TestAgent", description="test", version="1.0.0",
            skills=[Skill(name="test", description="test", input_schema={}, output_schema={})],
            endpoint="http://localhost:9999",
        ))
        init_coordinator(reg)

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/query", json={"question": "hello"})
        # May fail due to agent not running, but should not be 400/503
        assert resp.status_code in (200, 500)
