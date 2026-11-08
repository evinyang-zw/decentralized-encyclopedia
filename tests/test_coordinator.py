"""Tests for the Coordinator (routing, dispatch wiring, aggregation)."""
from __future__ import annotations

import pytest

from src.agents.coordinator import Coordinator, SubTask
from src.llm.base import LLMProviderError
from src.orchestrator.dispatcher import Dispatcher, DispatchResult
from src.orchestrator.registry import AgentRegistry
from src.orchestrator.router import Router
from src.protocol.models import (
    AgentCard,
    Message,
    Part,
    Skill,
    Task,
    TaskState,
    TaskStatus,
)


def _card(name: str, url: str = "http://localhost:8001", skill: str = "search") -> AgentCard:
    return AgentCard(
        name=name,
        description=f"{name} description",
        version="0.2.0",
        url=url,
        skills=[Skill(id=skill, name=skill, description=skill)],
    )


def _setup(llm=None) -> Coordinator:
    reg = AgentRegistry()
    reg.register_sync(_card("WikipediaAgent", "http://localhost:8001"))
    reg.register_sync(_card("ArxivAgent", "http://localhost:8002"))
    reg.register_sync(_card("WikidataAgent", "http://localhost:8005"))
    router = Router(registry=reg, llm=llm)
    dispatcher = Dispatcher(timeout=1.0, max_retries=0)
    return Coordinator(registry=reg, router=router, dispatcher=dispatcher, llm=llm)


def _agent_task(*messages: str, data: dict | None = None) -> Task:
    parts = [Part(kind="text", text=m) for m in messages]
    if data is not None:
        parts.append(Part(kind="data", data=data))
    return Task(
        id="t1",
        status=TaskStatus(state=TaskState.COMPLETED),
        history=[Message(role="agent", parts=parts)],
    )


class TestRuleRouting:
    def test_rule_decompose(self):
        coord = _setup()
        subtasks = coord._rule_decompose("什么是Python百科")
        assert len(subtasks) > 0
        assert subtasks[0].query == "什么是Python百科"
        assert "WikipediaAgent" in subtasks[0].target_agents

    def test_people_question_routes_to_wiki_and_wikidata(self):
        coord = _setup()
        subtasks = coord._rule_decompose("爱因斯坦在哪所大学任教？")
        assert {"WikipediaAgent", "WikidataAgent"}.issubset(set(subtasks[0].target_agents))

    def test_no_match_falls_back_to_first_agents(self):
        coord = _setup()
        subtasks = coord._rule_decompose("zzz 无法匹配的问题 zzz")
        assert subtasks[0].target_agents  # fallback non-empty
        assert any("兜底" in line for line in coord._process_log)


class TestAggregation:
    def test_rule_aggregate_renders_agent_sections(self):
        coord = _setup()
        results = [
            DispatchResult(
                card=_card("WikipediaAgent"),
                task=_agent_task(
                    "Found 1 articles",
                    data={"results": [{"title": "Python", "snippet": "a language", "url": "http://x"}]},
                ),
            ),
            DispatchResult(
                card=_card("ArxivAgent", "http://localhost:8002"),
                task=_agent_task("Found 1 papers", data={"results": [{"title": "Paper A"}]}),
            ),
        ]
        answer = coord._rule_aggregate(results)
        assert "WikipediaAgent" in answer
        assert "ArxivAgent" in answer
        assert "Python" in answer
        assert "多源检索结果" in answer
        assert "来源：" in answer

    def test_rule_aggregate_empty(self):
        coord = _setup()
        answer = coord._rule_aggregate([])
        assert "未从任何知识源获得有效结果" in answer

    def test_failed_sources_are_listed(self):
        coord = _setup()
        results = [
            DispatchResult(card=_card("WikipediaAgent"), task=_agent_task("Found 1", data={"results": [{"title": "X"}]})),
            DispatchResult(card=_card("WikidataAgent"), error="403 Forbidden"),
        ]
        answer = coord._rule_aggregate(results)
        assert "失败" in answer
        assert "403 Forbidden" in answer

    def test_mock_source_is_labelled(self):
        coord = _setup()
        results = [
            DispatchResult(
                card=_card("WikidataAgent"),
                task=_agent_task(
                    "Found knowledge about Albert Einstein（本地快照）",
                    data={"source": "local-mock", "results": [{"title": "Albert Einstein", "birth": "1879"}]},
                ),
            )
        ]
        answer = coord._rule_aggregate(results)
        assert "本地 mock 快照" in answer


class _FailingLLM:
    async def chat(self, messages, **kwargs):
        raise LLMProviderError("all models failed")


class TestLLMFailureFallback:
    @pytest.mark.asyncio
    async def test_decompose_falls_back_on_provider_error(self):
        coord = _setup(llm=_FailingLLM())
        subtasks = await coord.decompose("量子计算有哪些开源实现？")
        assert subtasks
        assert subtasks[0].target_agents
        assert any("降级到规则路由" in line for line in coord._process_log)

    @pytest.mark.asyncio
    async def test_aggregate_falls_back_on_provider_error(self):
        coord = _setup(llm=_FailingLLM())
        results = [
            DispatchResult(card=_card("ArxivAgent"), task=_agent_task("Found 1 papers"))
        ]
        answer = await coord.aggregate("量子计算", results)
        assert "ArxivAgent" in answer
        assert any("降级到规则聚合" in line for line in coord._process_log)


class TestDispatchWiring:
    @pytest.mark.asyncio
    async def test_dispatch_skips_unknown_agents(self):
        coord = _setup()
        results = await coord.dispatch([SubTask(query="q", target_agents=["NotRegistered"])])
        assert results == []
        assert any("跳过不可用 agent" in line for line in coord._process_log)

    @pytest.mark.asyncio
    async def test_dispatch_uses_dispatcher(self, monkeypatch):
        coord = _setup()

        async def fake_dispatch(tasks, send_fn, max_concurrency=5):
            return [DispatchResult(card=card, task=_agent_task("ok")) for card, _ in tasks]

        monkeypatch.setattr(coord.dispatcher, "dispatch", fake_dispatch)
        results = await coord.dispatch([SubTask(query="q", target_agents=["WikipediaAgent"])])
        assert len(results) == 1
        assert results[0].ok
