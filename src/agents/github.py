"""GitHub Agent — searches GitHub API for repositories."""
from __future__ import annotations

import httpx

from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task


class GithubAgent(BaseAgent):
    API_URL = "https://api.github.com/search/repositories"

    async def handle_message(self, message: Message, task: Task) -> Message:
        query = self.extract_text(message)
        limit = message.metadata.get("limit", 5)

        results = await self._search_github(query, limit)

        parts = [
            Part(type="text", text=f"Found {len(results)} repositories for '{query}'"),
            Part(type="data", data={"results": results}),
        ]
        return Message(role="agent", parts=parts)

    async def _search_github(self, query: str, max_results: int) -> list[dict]:
        params = {"q": query, "per_page": max_results, "sort": "stars", "order": "desc"}
        headers = {"Accept": "application/vnd.github.v3+json"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self.API_URL, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "stars": item["stargazers_count"],
                    "url": item["html_url"],
                }
                for item in data.get("items", [])[:max_results]
            ]
