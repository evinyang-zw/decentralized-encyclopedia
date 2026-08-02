"""Wikipedia Agent — searches Wikipedia API for article summaries."""
from __future__ import annotations

import httpx

from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task


class WikipediaAgent(BaseAgent):
    async def handle_message(self, message: Message, task: Task) -> Message:
        query = self.extract_text(message)
        lang = message.metadata.get("lang", "en")
        limit = message.metadata.get("limit", 5)

        results = await self._search_wikipedia(query, lang, limit)

        parts = [
            Part(type="text", text=f"Found {len(results)} Wikipedia articles for '{query}'"),
            Part(type="data", data={"results": results}),
        ]
        return Message(role="agent", parts=parts)

    async def _search_wikipedia(self, query: str, lang: str, limit: int) -> list[dict]:
        url = f"https://{lang}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return [
                {"title": r["title"], "snippet": r.get("snippet", "")}
                for r in data.get("query", {}).get("search", [])
            ]
