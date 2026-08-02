"""Integration tests — end-to-end A2A protocol flow."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from src.protocol.models import AgentCard, Skill, Message, Part, Task
from src.protocol.server import A2AServer


class EchoAgent(A2AServer):
    async def handle_message(self, message: Message, task: Task) -> Message:
        text = message.parts[0].text if message.parts else ""
        return Message(role="agent", parts=[Part(type="text", text=f"Echo: {text}")])


class TestIntegration:
    @pytest.mark.asyncio
    async def test_client_server_roundtrip(self):
        card = AgentCard(
            name="EchoAgent", description="Echo", version="1.0.0",
            skills=[Skill(name="echo", description="echo", input_schema={}, output_schema={})],
            endpoint="http://localhost:9999",
        )
        server = EchoAgent(card=card)
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as http:
            resp = await http.get("/.well-known/agent.json")
            assert resp.status_code == 200
            card_data = resp.json()
            assert card_data["name"] == "EchoAgent"

            resp = await http.post("/", json={
                "jsonrpc": "2.0",
                "method": "message/send",
                "id": 1,
                "params": {
                    "message": {"role": "user", "parts": [{"type": "text", "text": "hello"}]},
                },
            })
            assert resp.status_code == 200
            data = resp.json()
            messages = data["result"]["messages"]
            assert any("Echo: hello" in m["parts"][0]["text"] for m in messages)

    @pytest.mark.asyncio
    async def test_task_lifecycle(self):
        card = AgentCard(
            name="EchoAgent", description="Echo", version="1.0.0",
            skills=[], endpoint="http://localhost:9999",
        )
        server = EchoAgent(card=card)
        transport = ASGITransport(app=server.app)

        async with AsyncClient(transport=transport, base_url="http://test") as http:
            resp = await http.post("/", json={
                "jsonrpc": "2.0", "method": "message/send", "id": 1,
                "params": {
                    "message": {"role": "user", "parts": [{"type": "text", "text": "test"}]},
                    "task_id": "test-task-1",
                },
            })
            task_id = resp.json()["result"]["task_id"]

            resp = await http.post("/", json={
                "jsonrpc": "2.0", "method": "task/get", "id": 2,
                "params": {"task_id": task_id},
            })
            assert resp.json()["result"]["state"] == "completed"

            resp = await http.post("/", json={
                "jsonrpc": "2.0", "method": "task/cancel", "id": 3,
                "params": {"task_id": task_id},
            })
            assert resp.json()["result"]["state"] == "canceled"
