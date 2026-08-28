from __future__ import annotations
import json
import logging
import re
from typing import Any

from src.orchestrator.registry import AgentRegistry
from src.protocol.models import AgentCard

logger = logging.getLogger(__name__)


class Router:
    KEYWORD_RULES = {
        "wiki|百科|定义|是什么|概念": ["WikipediaAgent"],
        "论文|研究|arxiv|学术|paper": ["ArxivAgent"],
        "代码|开源|gitlab|github|项目|repo": ["GithubAgent"],
        "天气|气候|温度|降雨|weather": ["WeatherAgent"],
        "数据|实体|关系|知识图谱|wikidata": ["WikidataAgent"],
    }

    def __init__(self, registry: AgentRegistry, llm: Any | None = None):
        self.registry = registry
        self.llm = llm

    def rule_match(self, query: str) -> list[AgentCard]:
        matched_names: set[str] = set()
        for pattern, agent_names in self.KEYWORD_RULES.items():
            if re.search(pattern, query, re.IGNORECASE):
                for name in agent_names:
                    card = self.registry.get_by_name(name)
                    if card and not self.registry.is_disabled(name):
                        matched_names.add(name)
        return [self.registry.get_by_name(n) for n in matched_names if self.registry.get_by_name(n)]

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
            return [self.registry.get_by_name(n) for n in names if isinstance(n, str) and self.registry.get_by_name(n)]
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("LLM route failed: %s", e)
            return []
