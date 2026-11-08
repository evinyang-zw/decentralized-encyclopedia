"""Wikipedia Agent — searches DBpedia Lookup API for entity summaries."""
from __future__ import annotations

import re

import httpx

from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task
from src.utils.query_translate import QueryTranslator

_HTML_TAG_RE = re.compile(r"<[^>]+>")


class WikipediaAgent(BaseAgent):
    API_URL = "https://lookup.dbpedia.org/api/search"

    def __init__(
        self,
        card: AgentCard,
        api_key: str | None = None,
        translator: QueryTranslator | None = None,
    ):
        super().__init__(card, api_key)
        self._translator = translator or QueryTranslator()

    async def handle_message(self, message: Message, task: Task) -> Message:
        raw = self.extract_text(message)
        # DBpedia Lookup is keyword-based and English-centric: translate first.
        query = (await self._translator.translate(raw)).strip() or raw
        limit = message.metadata.get("limit", 5)

        results = await self._search(query, limit)

        parts = [
            Part(kind="text", text=f"Found {len(results)} articles for '{query}'"),
            Part(kind="data", data={"results": results}),
        ]
        return Message(role="agent", parts=parts)

    async def _search(self, query: str, max_results: int) -> list[dict]:
        params = {"query": query, "format": "json", "maxResults": max_results}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self.API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for doc in data.get("docs", []):
                label = self._first(doc.get("label", []))
                comment = self._first(doc.get("comment", []))
                resource = self._first(doc.get("resource", []))
                results.append({
                    "title": self._strip_html(label),
                    "snippet": self._strip_html(comment),
                    "url": resource,
                })
            return results

    @staticmethod
    def _first(lst: list) -> str:
        return lst[0] if lst else ""

    @staticmethod
    def _strip_html(text: str) -> str:
        return _HTML_TAG_RE.sub("", text)
