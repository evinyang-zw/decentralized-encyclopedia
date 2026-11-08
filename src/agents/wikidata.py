"""Wikidata Agent — searches Wikidata Entity Search API with mock fallback."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task
from src.utils.query_translate import QueryTranslator

logger = logging.getLogger(__name__)

MOCK_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "mock" / "wikidata.json"
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
# Wikimedia asks every client to identify itself; a browser-like default UA is
# rejected with HTTP 403, which used to silently push this agent to mock data.
USER_AGENT = (
    "DecentralizedEncyclopedia/0.2 "
    "(https://github.com/evinyang-zw/decentralized-encyclopedia)"
)


class WikidataAgent(BaseAgent):
    SEARCH_URL = "https://www.wikidata.org/w/api.php"

    def __init__(
        self,
        card: AgentCard,
        api_key: str | None = None,
        translator: QueryTranslator | None = None,
    ):
        super().__init__(card, api_key)
        self._translator = translator or QueryTranslator()
        self._fallback_data = self._load_fallback()

    def _load_fallback(self) -> dict:
        if MOCK_DATA_PATH.exists():
            return json.loads(MOCK_DATA_PATH.read_text())
        return {}

    async def handle_message(self, message: Message, task: Task) -> Message:
        raw = self.extract_text(message).strip()
        query = (await self._translator.translate(raw)).strip() or raw
        # Use language=zh for CJK queries, language=en otherwise
        lang = "zh" if self._contains_cjk(raw) else "en"
        results = await self._search_entities(query, lang=lang)
        if results:
            return Message(
                role="agent",
                parts=[
                    Part(kind="text", text=f"Found {len(results)} entities for '{raw}'"),
                    Part(kind="data", data={"source": "wikidata-api", "results": results}),
                ],
            )
        # Fallback to local mock data (search with aliases)
        raw_lower = raw.lower()
        for name, data in self._fallback_data.items():
            aliases = [name.lower()] + [a.lower() for a in data.get("_aliases", [])]
            if any(raw_lower in alias or alias in raw_lower for alias in aliases):
                entity = {k: v for k, v in data.items() if not k.startswith("_")}
                return Message(
                    role="agent",
                    parts=[
                        Part(kind="text", text=f"Found knowledge about {name}（本地快照）"),
                        Part(
                            kind="data",
                            data={"source": "local-mock", "results": [{"title": name, **entity}]},
                        ),
                    ],
                )
        return Message(
            role="agent",
            parts=[Part(kind="text", text=f"未找到与 '{raw}' 相关的知识图谱数据")],
        )

    async def _search_entities(self, query: str, lang: str = "en", limit: int = 5) -> list[dict]:
        params: dict[str, Any] = {
            "action": "wbsearchentities",
            "search": query,
            "language": lang,
            "format": "json",
            "limit": limit,
        }
        try:
            headers = {"User-Agent": USER_AGENT}
            async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
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
