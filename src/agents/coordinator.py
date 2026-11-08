"""Coordinator — problem decomposition, routing, parallel dispatch and aggregation.

Note on topology: this is a **centralized coordinator** (hub-and-spoke), not a
peer-to-peer "decentralized" mesh — every domain agent only talks to the
coordinator over the A2A subset. The repository name is historical; the
architecture is documented in README ("Architecture").
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from src.agents.base import BaseAgent
from src.orchestrator.dispatcher import Dispatcher, DispatchResult
from src.orchestrator.registry import AgentRegistry
from src.orchestrator.router import Router
from src.protocol.models import AgentCard, Message, Part, Task

logger = logging.getLogger(__name__)

_TITLE_KEYS = ("title", "name", "label")
_SNIPPET_KEYS = ("snippet", "description", "abstract", "comment")
_URL_KEYS = ("url", "resource", "concepturi", "link")


class DecomposedTask(BaseModel):
    query: str
    agents: list[str] = []


@dataclass
class SubTask:
    query: str
    target_agents: list[str]


class Coordinator(BaseAgent):
    def __init__(
        self,
        registry: AgentRegistry,
        router: Router,
        dispatcher: Dispatcher,
        llm: Any | None = None,
        api_key: str | None = None,
        url: str = "http://localhost:8000",
    ):
        card = AgentCard(
            name="Coordinator",
            description="问题分解、路由、并行调度与结果聚合（编排层，非 A2A 协议的一部分）",
            version="0.2.0",
            protocolVersion="0.3.0",
            url=url,
        )
        super().__init__(card, api_key)
        self.registry = registry
        self.router = router
        self.dispatcher = dispatcher
        self.llm = llm
        self._process_log: list[str] = []

    async def handle_message(self, message: Message, task: Task) -> Message:
        query = self.extract_text(message)
        self._process_log = []
        subtasks = await self.decompose(query)
        results = await self.dispatch(subtasks)
        answer = await self.aggregate(query, results)
        return Message(role="agent", parts=[Part(kind="text", text=answer)])

    # ------------------------------------------------------------- decompose
    async def decompose(self, query: str) -> list[SubTask]:
        if self.llm:
            return await self._llm_decompose(query)
        return self._rule_decompose(query)

    def _rule_decompose(self, query: str) -> list[SubTask]:
        agents = self.router.rule_match(query)
        if not agents:
            agents = self.registry.get_enabled()[:3]
            self._process_log.append(
                f"路由: 规则未命中，兜底启用前 {len(agents)} 个 agent → "
                + ", ".join(a.name for a in agents)
            )
        else:
            self._process_log.append(
                f"路由: 规则命中 {len(agents)} 个 agent → " + ", ".join(a.name for a in agents)
            )
        return [SubTask(query=query, target_agents=[a.name for a in agents])]

    async def _llm_decompose(self, query: str) -> list[SubTask]:
        from src.llm.prompts import DECOMPOSE_PROMPT

        agents_str = ", ".join(a.name for a in self.registry.get_all())
        prompt = DECOMPOSE_PROMPT.format(available_agents=agents_str, query=query)
        try:
            response = await self.llm.chat([{"role": "user", "content": prompt}])
            items = json.loads(response)
            validated = [DecomposedTask(**item) for item in items if isinstance(item, dict)]
            subtasks = [
                SubTask(query=t.query, target_agents=t.agents) for t in validated if t.query
            ]
            if not subtasks:
                raise ValueError("LLM returned no usable subtasks")
            self._process_log.append(f"路由: LLM 分解为 {len(subtasks)} 个子任务")
            return subtasks
        except (json.JSONDecodeError, ValidationError, KeyError, ValueError, TypeError) as exc:
            logger.warning("LLM decompose failed, falling back to rules: %s", exc)
            self._process_log.append(f"路由: LLM 分解失败（{type(exc).__name__}），降级到规则路由")
            return self._rule_decompose(query)
        except Exception as exc:  # LLMProviderError and transport errors
            logger.warning("LLM provider failed during decompose, falling back: %s", exc)
            self._process_log.append(f"路由: LLM 调用失败（{type(exc).__name__}），降级到规则路由")
            return self._rule_decompose(query)

    # ------------------------------------------------------------- dispatch
    async def dispatch(self, subtasks: list[SubTask]) -> list[DispatchResult]:
        tasks_to_send: list[tuple[AgentCard, Message]] = []
        for st in subtasks:
            for agent_name in st.target_agents:
                card = self.registry.get_by_name(agent_name)
                if card is None or self.registry.is_disabled(agent_name):
                    self._process_log.append(f"分发: 跳过不可用 agent {agent_name}")
                    continue
                msg = Message(role="user", parts=[Part(kind="text", text=st.query)])
                tasks_to_send.append((card, msg))

        self._process_log.append(f"分发: 向 {len(tasks_to_send)} 个 agent 发送请求（并行）")

        async def send(client, msg):  # type: ignore[no-untyped-def]
            return await client.send_message(msg)

        results = await self.dispatcher.dispatch(tasks_to_send, send_fn=send)
        ok = sum(1 for r in results if r.ok)
        self._process_log.append(f"收集: {ok}/{len(results)} 个 agent 返回结果")
        for r in results:
            if not r.ok:
                self._process_log.append(f"收集: {r.card.name} 失败 → {r.error}")
        return results

    # ------------------------------------------------------------- aggregate
    async def aggregate(self, query: str, results: list[DispatchResult]) -> str:
        if self.llm:
            llm_answer = await self._llm_aggregate(query, results)
            if llm_answer:
                return llm_answer
        return self._rule_aggregate(results)

    def _rule_aggregate(self, results: list[DispatchResult]) -> str:
        ok_results = [r for r in results if r.ok]
        if not ok_results:
            return "未从任何知识源获得有效结果。请换个问法，或检查各 Agent 是否在线。"

        sections: list[str] = []
        empty_agents: list[str] = []
        for result in ok_results:
            body = self._render_result(result)
            if body:
                sections.append(body)
            else:
                empty_agents.append(result.card.name)

        if not sections:
            return "各知识源均返回空结果。可尝试更具体的关键词。"

        header = f"### 多源检索结果（{len(sections)}/{len(results)} 个数据源有效）"
        source_names = [r.card.name for r in ok_results if r.card.name not in empty_agents]
        footer_parts = ["来源：" + "、".join(source_names)]
        failed = [r for r in results if not r.ok]
        if failed:
            footer_parts.append("失败：" + "、".join(f"{r.card.name}（{r.error}）" for r in failed))
        if empty_agents:
            footer_parts.append("无结果：" + "、".join(empty_agents))
        return "\n\n".join([header, *sections, "---", "；".join(footer_parts)])

    def _render_result(self, result: DispatchResult) -> str | None:
        assert result.task is not None
        task = result.task
        agent_name = result.card.name
        skill_name = result.card.skills[0].name if result.card.skills else "检索"
        lines: list[str] = [f"**{agent_name} · {skill_name}**"]

        text_summary = ""
        items: list[dict[str, Any]] = []
        mock = False
        for message in task.history:
            if message.role != "agent":
                continue
            for part in message.parts:
                if part.kind == "text" and part.text:
                    text_summary = part.text
                elif part.kind == "data" and isinstance(part.data, dict):
                    if part.data.get("source") == "local-mock":
                        mock = True
                    raw_items = part.data.get("results")
                    if isinstance(raw_items, list):
                        items.extend(i for i in raw_items if isinstance(i, dict))
                    elif part.data:
                        items.append(part.data)

        if text_summary:
            lines.append(f"> {text_summary}")
        rendered = [self._render_item(item) for item in items[:5]]
        rendered = [r for r in rendered if r]
        lines.extend(f"- {r}" for r in rendered)
        if mock:
            lines.append("- *(数据来源：本地 mock 快照——Wikidata 在线 API 不可用时的兜底)*")
        if not rendered and not text_summary:
            return None
        if "Found 0" in text_summary and not rendered:
            return None
        return "\n".join(lines)

    @staticmethod
    def _render_item(item: dict[str, Any]) -> str | None:
        title = next((str(item[k]) for k in _TITLE_KEYS if item.get(k)), "")
        snippet = next((str(item[k]) for k in _SNIPPET_KEYS if item.get(k)), "")
        url = next((str(item[k]) for k in _URL_KEYS if item.get(k)), "")

        if title:
            line = f"**{title}**"
            if snippet:
                line += f" — {snippet[:160]}"
            if url:
                line += f"（[链接]({url})）"
            else:
                extra = [
                    f"{k}: {v}"
                    for k, v in item.items()
                    if k not in _TITLE_KEYS + _SNIPPET_KEYS + _URL_KEYS and not k.startswith("_")
                ]
                if extra:
                    line += "（" + "；".join(str(e) for e in extra[:4]) + "）"
            return line

        # Generic dict (e.g. local mock entity with type/birth/employer …)
        fields = [f"{k}: {v}" for k, v in item.items() if not k.startswith("_") and v]
        if not fields:
            return None
        return "；".join(str(f) for f in fields[:6])

    async def _llm_aggregate(self, query: str, results: list[DispatchResult]) -> str | None:
        from src.llm.prompts import AGGREGATE_PROMPT

        blocks: list[str] = []
        for result in results:
            if not result.ok or result.task is None:
                continue
            for message in result.task.history:
                if message.role != "agent":
                    continue
                for part in message.parts:
                    if part.kind == "text" and part.text:
                        blocks.append(f"[{result.card.name}] {part.text}")
                    elif part.kind == "data" and part.data:
                        payload = json.dumps(part.data, ensure_ascii=False)[:1500]
                        blocks.append(f"[{result.card.name}] {payload}")
        if not blocks:
            return None
        prompt = AGGREGATE_PROMPT.format(query=query, results="\n".join(blocks))
        try:
            answer = await self.llm.chat([{"role": "user", "content": prompt}])
            self._process_log.append("聚合: LLM 综合生成")
            return answer or None
        except Exception as exc:  # LLMProviderError / transport
            logger.warning("LLM aggregate failed, falling back to rules: %s", exc)
            self._process_log.append(f"聚合: LLM 失败（{type(exc).__name__}），降级到规则聚合")
            return None
