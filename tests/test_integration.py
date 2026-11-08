"""Integration + contract tests for the A2A v0.3-style subset.

These tests exercise the real ``A2AClient`` against a real ``A2AServer`` app
through an in-process ASGI transport, so the wire format (card path, JSON-RPC
method names, Task shape, error codes) is asserted end to end.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from src.protocol.client import A2AClient
from src.protocol.models import (
    A2AError,
    AgentCard,
    Message,
    Part,
    Skill,
    Task,
    TaskState,
    TaskStatus,
)
from src.protocol.server import CARD_PATH, A2AServer


class EchoAgent(A2AServer):
    async def handle_message(self, message: Message, task: Task) -> Message:
        text = message.parts[0].text if message.parts else ""
        return Message(role="agent", parts=[Part(kind="text", text=f"Echo: {text}")])


class FailingAgent(A2AServer):
    async def handle_message(self, message: Message, task: Task) -> Message:
        raise RuntimeError("backend exploded")


def _card(name: str = "EchoAgent") -> AgentCard:
    return AgentCard(
        name=name,
        description="Echo",
        version="0.2.0",
        url="http://localhost:9999",
        skills=[Skill(id="echo", name="echo", description="echo back the input")],
    )


def _client(server: A2AServer) -> A2AClient:
    transport = ASGITransport(app=server.app)
    http = AsyncClient(transport=transport, base_url="http://test")
    return A2AClient(base_url="http://test", http_client=http)


async def _rpc(http: AsyncClient, method: str, params: dict, req_id: int = 1) -> dict:
    resp = await http.post(
        "/", json={"jsonrpc": "2.0", "method": method, "id": req_id, "params": params}
    )
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
class TestClientServerRoundtrip:
    async def test_agent_card_is_served_at_the_canonical_path(self):
        server = EchoAgent(card=_card())
        async with AsyncClient(
            transport=ASGITransport(app=server.app), base_url="http://test"
        ) as http:
            resp = await http.get(CARD_PATH)
            assert resp.status_code == 200
            card = resp.json()
            assert card["name"] == "EchoAgent"
            assert card["protocolVersion"] == "0.3.0"
            assert card["preferredTransport"] == "JSONRPC"
            assert card["capabilities"]["streaming"] is False
            assert card["skills"][0]["id"] == "echo"

            # the v0.3 path is canonical; the pre-v0.3 path must not be served
            resp = await http.get("/.well-known/agent.json")
            assert resp.status_code == 404

    async def test_client_sends_message_and_gets_task(self):
        server = EchoAgent(card=_card())
        client = _client(server)
        try:
            task = await client.send_message(
                Message(role="user", parts=[Part(kind="text", text="hello")])
            )
        finally:
            await client.close()
        assert task.kind == "task"
        assert task.status.state == TaskState.COMPLETED
        agent_messages = [m for m in task.history if m.role == "agent"]
        assert agent_messages and agent_messages[-1].parts[0].text == "Echo: hello"

    async def test_client_get_task_after_send(self):
        server = EchoAgent(card=_card())
        client = _client(server)
        try:
            task = await client.send_message(
                Message(role="user", parts=[Part(kind="text", text="ping")])
            )
            fetched = await client.get_task(task.id)
        finally:
            await client.close()
        assert fetched.id == task.id
        assert fetched.status.state == TaskState.COMPLETED
        assert len(fetched.history) == 2  # user message + agent response


@pytest.mark.asyncio
class TestTaskLifecycleSemantics:
    async def test_cancel_on_terminal_task_returns_task_not_cancelable(self):
        server = EchoAgent(card=_card())
        async with AsyncClient(
            transport=ASGITransport(app=server.app), base_url="http://test"
        ) as http:
            async def _send():
                return await _rpc(
                    http,
                    "message/send",
                    {"message": {"role": "user", "parts": [{"kind": "text", "text": "x"}]}},
                )

            payload = await _send()
            task_id = payload["result"]["id"]
            assert payload["result"]["status"]["state"] == "completed"

            payload = await _rpc(http, "tasks/cancel", {"id": task_id}, req_id=2)
            assert payload["error"]["code"] == -32002
            assert "not cancelable" in payload["error"]["message"].lower()

    async def test_cancel_on_pending_task_succeeds(self):
        server = EchoAgent(card=_card())
        server.tasks.put("pending-1", Task(id="pending-1"))
        async with AsyncClient(
            transport=ASGITransport(app=server.app), base_url="http://test"
        ) as http:
            payload = await _rpc(http, "tasks/cancel", {"id": "pending-1"})
        assert payload["result"]["status"]["state"] == "canceled"

    async def test_send_to_terminal_task_is_rejected(self):
        server = EchoAgent(card=_card())
        async with AsyncClient(
            transport=ASGITransport(app=server.app), base_url="http://test"
        ) as http:
            payload = await _rpc(
                http,
                "message/send",
                {"message": {"role": "user", "parts": [{"kind": "text", "text": "x"}]}},
            )
            task_id = payload["result"]["id"]
            assert payload["result"]["status"]["state"] == "completed"

            payload = await _rpc(
                http,
                "message/send",
                {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "again"}],
                        "taskId": task_id,
                    }
                },
                req_id=2,
            )
        assert payload["error"]["code"] == -32004

    async def test_failing_agent_returns_failed_task_not_http_error(self):
        server = FailingAgent(card=_card())
        async with AsyncClient(
            transport=ASGITransport(app=server.app), base_url="http://test"
        ) as http:
            payload = await _rpc(
                http,
                "message/send",
                {"message": {"role": "user", "parts": [{"kind": "text", "text": "x"}]}},
            )
        assert "result" in payload
        assert payload["result"]["status"]["state"] == "failed"
        assert payload["result"]["status"]["message"]["metadata"]["error"]


@pytest.mark.asyncio
class TestJSONRPCErrors:
    async def test_tasks_get_not_found(self):
        server = EchoAgent(card=_card())
        async with AsyncClient(
            transport=ASGITransport(app=server.app), base_url="http://test"
        ) as http:
            payload = await _rpc(http, "tasks/get", {"id": "missing"})
        assert payload["error"]["code"] == -32001

    async def test_unknown_method(self):
        server = EchoAgent(card=_card())
        async with AsyncClient(
            transport=ASGITransport(app=server.app), base_url="http://test"
        ) as http:
            payload = await _rpc(http, "message/stream", {})
        assert payload["error"]["code"] == -32601

    async def test_invalid_message_params(self):
        server = EchoAgent(card=_card())
        async with AsyncClient(
            transport=ASGITransport(app=server.app), base_url="http://test"
        ) as http:
            payload = await _rpc(http, "message/send", {"message": {"role": "user"}})
        assert payload["error"]["code"] == -32602

    async def test_client_raises_a2a_error_on_error_payload(self):
        card = AgentCard(name="NoAuth", version="0.2.0", url="http://x")
        server = EchoAgent(card=card, api_key="secret")
        client = _client(server)
        try:
            with pytest.raises(A2AError) as excinfo:
                await client.send_message(Message(role="user", parts=[Part(kind="text", text="x")]))
        finally:
            await client.close()
        assert excinfo.value.code == -32600

    async def test_unknown_task_state_is_not_accepted(self):
        """TaskStatus only accepts the spec's enum values."""
        with pytest.raises(ValidationError):
            Task(id="t", status=TaskStatus(state="teleported"))  # type: ignore[arg-type]
