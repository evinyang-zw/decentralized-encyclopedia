"""Coordinator Agent — problem decomposition, routing, and result aggregation."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from src.agents.base import BaseAgent
from src.orchestrator.registry import AgentRegistry
from src.orchestrator.router import Router
from src.orchestrator.dispatcher import Dispatcher
from src.protocol.models import AgentCard, Message, Part, Task

logger = logging.getLogger(__name__)


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
    ):
        card = AgentCard(
            name="Coordinator",
            description="问题分解、路由、聚合",
            version="1.0.0",
            skills=[],
            endpoint="http://localhost:8010",
        )
        super().__init__(card, api_key)
        self.registry = registry
        self.router = router
        self.dispatcher = dispatcher
        self.llm = llm

    async def handle_message(self, message: Message, task: Task) -> Message:
        query = self.extract_text(message)
        subtasks = await self.decompose(query)
        results = await self.dispatch(subtasks)
        answer = await self.aggregate(query, results)
        return Message(role="agent", parts=[Part(type="text", text=answer)])

    async def decompose(self, query: str) -> list[SubTask]:
        if self.llm:
            return await self._llm_decompose(query)
        return self._rule_decompose(query)

    def _rule_decompose(self, query: str) -> list[SubTask]:
        agents = self.router.rule_match(query)
        if not agents:
            agents = self.registry.get_all()[:3]
        return [SubTask(query=query, target_agents=[a.name for a in agents])]

    async def _llm_decompose(self, query: str) -> list[SubTask]:
        from src.llm.prompts import DECOMPOSE_PROMPT
        agents_str = ", ".join(a.name for a in self.registry.get_all())
        prompt = DECOMPOSE_PROMPT.format(available_agents=agents_str, query=query)
        try:
            response = await self.llm.chat([{"role": "user", "content": prompt}])
            items = json.loads(response)
            validated = [DecomposedTask(**item) for item in items]
            return [SubTask(query=t.query, target_agents=t.agents) for t in validated]
        except (json.JSONDecodeError, ValidationError, KeyError) as e:
            logger.warning("LLM decompose failed, falling back to rules: %s", e)
            return self._rule_decompose(query)

    async def dispatch(self, subtasks: list[SubTask]) -> list[Message]:
        tasks_to_send = []
        for st in subtasks:
            for agent_name in st.target_agents:
                card = self.registry.get_by_name(agent_name)
                if card:
                    msg = Message(role="user", parts=[Part(type="text", text=st.query)])
                    tasks_to_send.append((card, msg))

        async def send(client, msg):
            return await client.send_message(msg)

        results = await self.dispatcher.dispatch(tasks_to_send, send_fn=send)
        messages = []
        for task_result in results:
            messages.extend(task_result.messages)
        return messages

    async def aggregate(self, query: str, results: list[Message]) -> str:
        if self.llm:
            return await self._llm_aggregate(query, results)
        return self._rule_aggregate(results)

    def _rule_aggregate(self, results: list[Message]) -> str:
        parts = []
        for msg in results:
            for part in msg.parts:
                if part.type == "text":
                    parts.append(part.text)
                elif part.type == "data" and isinstance(part.data, dict):
                    parts.append(str(part.data))
        return "\n\n".join(parts) if parts else "No results found."

    async def _llm_aggregate(self, query: str, results: list[Message]) -> str:
        from src.llm.prompts import AGGREGATE_PROMPT
        results_text = "\n".join(
            p.text for msg in results for p in msg.parts if p.type == "text" and p.text
        )
        prompt = AGGREGATE_PROMPT.format(query=query, results=results_text)
        try:
            return await self.llm.chat([{"role": "user", "content": prompt}])
        except Exception as e:
            logger.warning("LLM aggregate failed, falling back to rules: %s", e)
            return self._rule_aggregate(results)
