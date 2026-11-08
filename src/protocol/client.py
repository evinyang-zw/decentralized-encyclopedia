"""A2A client — HTTP JSON-RPC caller for inter-agent communication.

Talks the A2A v0.3-style subset implemented by :class:`src.protocol.server.A2AServer`.
"""
from __future__ import annotations

from typing import Any

import httpx

from src.protocol.models import A2AError, AgentCard, Message, Task
from src.protocol.server import CARD_PATH


class A2AClient:
    _next_id = 0

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        headers = {}
        if api_key:
            headers["X-A2A-API-Key"] = api_key
        self._owns_http = http_client is None
        self.http = http_client or httpx.AsyncClient(timeout=30.0, headers=headers)

    def _next_request_id(self) -> int:
        A2AClient._next_id += 1
        return A2AClient._next_id

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._next_request_id(),
            "params": params,
        }
        resp = await self.http.post(f"{self.base_url}/", json=payload)
        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()
            raise
        error = data.get("error") if isinstance(data, dict) else None
        if error:
            raise A2AError(
                code=error.get("code", -32603),
                message=error.get("message", "unknown error"),
                data=error.get("data"),
            )
        resp.raise_for_status()
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, dict):
            raise A2AError(code=-32603, message=f"Malformed JSON-RPC result: {data!r}")
        return result

    async def get_agent_card(self) -> AgentCard:
        resp = await self.http.get(f"{self.base_url}{CARD_PATH}")
        resp.raise_for_status()
        return AgentCard(**resp.json())

    async def send_message(
        self,
        message: Message,
        task_id: str | None = None,
        context_id: str | None = None,
    ) -> Task:
        if task_id and not message.taskId:
            message = message.model_copy(update={"taskId": task_id})
        if context_id and not message.contextId:
            message = message.model_copy(update={"contextId": context_id})
        result = await self._rpc("message/send", {"message": message.model_dump()})
        return Task(**result)

    async def get_task(self, task_id: str) -> Task:
        result = await self._rpc("tasks/get", {"id": task_id})
        return Task(**result)

    async def cancel_task(self, task_id: str) -> Task:
        result = await self._rpc("tasks/cancel", {"id": task_id})
        return Task(**result)

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()
