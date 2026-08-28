"""arXiv Agent — searches arXiv API for academic papers."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task
from src.utils.query_translate import QueryTranslator


class ArxivAgent(BaseAgent):
    API_URL = "https://export.arxiv.org/api/query"

    def __init__(self, card: AgentCard, api_key: str | None = None, translator: QueryTranslator | None = None):
        super().__init__(card, api_key)
        self._translator = translator or QueryTranslator()

    async def handle_message(self, message: Message, task: Task) -> Message:
        raw = self.extract_text(message)
        query = await self._translator.translate(raw)
        limit = message.metadata.get("limit", 5)
        results = await self._search_arxiv(query, limit)
        parts = [
            Part(type="text", text=f"Found {len(results)} papers for '{query}'"),
            Part(type="data", data={"results": results}),
        ]
        return Message(role="agent", parts=parts)

    async def _search_arxiv(self, query: str, max_results: int) -> list[dict]:
        if not query.strip():
            return []
        params = {"search_query": f"all:{query}", "max_results": max_results, "sortBy": "relevance"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(self.API_URL, params=params)
            resp.raise_for_status()
            return self._parse_arxiv_response(resp.text)

    @staticmethod
    def _parse_arxiv_response(xml_text: str) -> list[dict]:
        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        results = []
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns)
            summary = entry.find("atom:summary", ns)
            link = entry.find("atom:id", ns)
            authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)]
            results.append({
                "title": title.text.strip() if title is not None else "",
                "abstract": summary.text.strip() if summary is not None else "",
                "url": link.text.strip() if link is not None else "",
                "authors": authors,
            })
        return results
