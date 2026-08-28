"""Wikidata Agent — searches Wikidata Entity Search API with mock fallback."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx

from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task

logger = logging.getLogger(__name__)

MOCK_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "mock" / "wikidata.json"
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


class WikidataAgent(BaseAgent):
    SEARCH_URL = "https://www.wikidata.org/w/api.php"

    def __init__(self, card: AgentCard, api_key: str | None = None):
        super().__init__(card, api_key)
        self._fallback_data = self._load_fallback()

    def _load_fallback(self) -> dict:
        if MOCK_DATA_PATH.exists():
            return json.loads(MOCK_DATA_PATH.read_text())
        return {}

    async def handle_message(self, message: Message, task: Task) -> Message:
        raw = self.extract_text(message).strip()
        # Use language=zh for CJK queries, language=en otherwise
        lang = "zh" if self._contains_cjk(raw) else "en"
        results = await self._search_entities(raw, lang=lang)
        if results:
            return Message(
                role="agent",
                parts=[
                    Part(type="text", text=f"Found {len(results)} entities for '{raw}'"),
                    Part(type="data", data={"results": results}),
                ],
            )
        # Fallback to local mock data (search with aliases)
        raw_lower = raw.lower()
        for name, data in self._fallback_data.items():
            aliases = [name.lower()] + [a.lower() for a in data.get("_aliases", [])]
            if any(raw_lower in alias or alias in raw_lower for alias in aliases):
                return Message(
                    role="agent",
                    parts=[
                        Part(type="text", text=f"Found knowledge about {name}"),
                        Part(type="data", data=data),
                    ],
                )
        return Message(
            role="agent",
            parts=[Part(type="text", text=f"未找到与 '{raw}' 相关的知识图谱数据")],
        )

    async def _search_entities(self, query: str, lang: str = "en", limit: int = 5) -> list[dict]:
        params = {
            "action": "wbsearchentities",
            "search": query,
            "language": lang,
            "format": "json",
            "limit": limit,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self.SEARCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                return [
                    {
                        "id": item.get("id", ""),
                        "label": item.get("label", ""),
                        "description": item.get("description", ""),
                        "url": item.get("concepturi", ""),
                    }
                    for item in data.get("search", [])
                ]
        except Exception as e:
            logger.warning("Wikidata API failed, falling back to mock data: %s", e)
            return []

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        return bool(_CJK_RE.search(text))
