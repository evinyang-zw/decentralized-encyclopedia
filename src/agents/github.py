"""GitLab Agent — searches GitLab API for projects."""
from __future__ import annotations

import httpx

from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task
from src.utils.query_translate import QueryTranslator


class GithubAgent(BaseAgent):
    API_URL = "https://gitlab.com/api/v4/projects"

    def __init__(self, card: AgentCard, api_key: str | None = None, translator: QueryTranslator | None = None):
        super().__init__(card, api_key)
        self._translator = translator or QueryTranslator()

    async def handle_message(self, message: Message, task: Task) -> Message:
        raw = self.extract_text(message)
        query = await self._translator.translate(raw)
        limit = message.metadata.get("limit", 5)
        results = await self._search(query, limit)
        parts = [
            Part(type="text", text=f"Found {len(results)} repositories for '{query}'"),
            Part(type="data", data={"results": results}),
        ]
        return Message(role="agent", parts=parts)

    async def _search(self, query: str, max_results: int) -> list[dict]:
        if not query.strip():
            return []
        params = {"search": query, "per_page": max_results, "order_by": "star_count"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self.API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "name": item["name"],
                    "description": item.get("description", "") or "",
                    "stars": item.get("star_count", 0),
                    "url": item.get("web_url", ""),
                }
                for item in data
            ]
