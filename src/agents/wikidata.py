"""Wikidata Agent — structured knowledge graph queries (mock data)."""
from __future__ import annotations

import json
from pathlib import Path

from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task

MOCK_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "mock" / "wikidata.json"


class WikidataAgent(BaseAgent):
    def __init__(self, card: AgentCard, api_key: str | None = None):
        super().__init__(card, api_key)
        self._data = self._load_mock_data()

    def _load_mock_data(self) -> dict:
        if MOCK_DATA_PATH.exists():
            return json.loads(MOCK_DATA_PATH.read_text())
        return {}

    async def handle_message(self, message: Message, task: Task) -> Message:
        query = self.extract_text(message).strip().lower()
        for entity_name, entity_data in self._data.items():
            if query in entity_name.lower():
                return Message(
                    role="agent",
                    parts=[
                        Part(type="text", text=f"Found knowledge about {entity_name}"),
                        Part(type="data", data=entity_data),
                    ],
                )
        return Message(
            role="agent",
            parts=[Part(type="text", text=f"未找到与 '{query}' 相关的知识图谱数据")],
        )
