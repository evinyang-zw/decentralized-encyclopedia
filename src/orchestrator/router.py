from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.orchestrator.registry import AgentRegistry
from src.protocol.models import AgentCard

logger = logging.getLogger(__name__)


class Router:
    # Ordered keyword rules → agent names. Order is intentional: it keeps
    # routing deterministic (the `single` evaluation config takes the first hit).
    KEYWORD_RULES: dict[str, list[str]] = {
        "人物|谁|哪位|哪所|大学|任教|学生|出生于|国籍|生平": ["WikipediaAgent", "WikidataAgent"],
        "百科|定义|是什么|概念|介绍": ["WikipediaAgent"],
        "论文|研究|arxiv|学术|paper|文献|综述": ["ArxivAgent"],
        "代码|开源|gitlab|github|项目|repo|仓库|实现": ["GithubAgent"],
        "天气|气候|温度|降雨|weather|气温|湿度": ["WeatherAgent"],
        "数据|实体|关系|知识图谱|wikidata|属性|图谱": ["WikidataAgent"],
    }

    def __init__(self, registry: AgentRegistry, llm: Any | None = None):
        self.registry = registry
        self.llm = llm

    def rule_match(self, query: str) -> list[AgentCard]:
        """Return agents matched by keyword rules, in rule order, de-duplicated."""
        matched: list[AgentCard] = []
        seen: set[str] = set()
        for pattern, agent_names in self.KEYWORD_RULES.items():
            if not re.search(pattern, query, re.IGNORECASE):
                continue
            for name in agent_names:
                if name in seen:
                    continue
                card = self.registry.get_by_name(name)
                if card is not None and not self.registry.is_disabled(name):
                    matched.append(card)
                    seen.add(name)
        return matched

    async def match(self, query: str) -> list[AgentCard]:
        rule_results = self.rule_match(query)
        if self.llm and len(rule_results) < 2:
            llm_results = await self.llm_match(query)
            seen = {c.name for c in rule_results}
            for c in llm_results:
                if c.name not in seen:
                    rule_results.append(c)
        return rule_results

    async def llm_match(self, query: str) -> list[AgentCard]:
        from src.llm.prompts import ROUTE_PROMPT
        agents_str = ", ".join(c.name for c in self.registry.get_all())
        prompt = ROUTE_PROMPT.format(agents=agents_str, query=query)
        try:
            response = await self.llm.chat([{"role": "user", "content": prompt}])
            names = json.loads(response)
            if not isinstance(names, list):
                logger.warning("LLM route returned non-list: %s", type(names))
                return []
            resolved: list[AgentCard] = []
            for name in names:
                if not isinstance(name, str):
                    continue
                card = self.registry.get_by_name(name)
                if card is not None:
                    resolved.append(card)
            return resolved
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("LLM route failed: %s", e)
            return []
