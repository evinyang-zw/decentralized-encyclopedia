"""A2A Client — HTTP JSON-RPC caller for inter-agent communication."""
from __future__ import annotations
import uuid

import httpx

from src.protocol.models import AgentCard, Message, Task, TaskState


class A2AClient:
    _next_id = 0

    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        headers = {}
        if api_key:
            headers["X-A2A-API-Key"] = api_key
        self.http = httpx.AsyncClient(timeout=30.0, headers=headers)

    def _next_request_id(self) -> int:
        A2AClient._next_id += 1
        return A2AClient._next_id

    async def get_agent_card(self) -> AgentCard:
        resp = await self.http.get(f"{self.base_url}/.well-known/agent.json")
        resp.raise_for_status()
        return AgentCard(**resp.json())

    async def send_message(self, message: Message, task_id: str | None = None) -> Task:
        payload = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": self._next_request_id(),
            "params": {
                "message": message.model_dump(),
                "task_id": task_id or str(uuid.uuid4()),
            },
        }
        resp = await self.http.post(f"{self.base_url}/", json=payload)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        messages = [Message(**m) for m in result.get("messages", []) if m.get("role") == "agent"]
        return Task(
            task_id=result.get("task_id", ""),
            state=TaskState.COMPLETED,
            messages=messages,
        )

    async def get_task(self, task_id: str) -> Task:
        payload = {
            "jsonrpc": "2.0",
            "method": "task/get",
            "id": self._next_request_id(),
            "params": {"task_id": task_id},
        }
        resp = await self.http.post(f"{self.base_url}/", json=payload)
        resp.raise_for_status()
        return Task(**resp.json().get("result", {}))

    async def cancel_task(self, task_id: str) -> Task:
        payload = {
            "jsonrpc": "2.0",
            "method": "task/cancel",
            "id": self._next_request_id(),
            "params": {"task_id": task_id},
        }
        resp = await self.http.post(f"{self.base_url}/", json=payload)
        resp.raise_for_status()
        return Task(task_id=task_id, state=TaskState.CANCELED)

    async def close(self):
        await self.http.aclose()
