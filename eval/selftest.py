"""Deterministic self-test for the evaluation harness (no network required).

Builds five fake A2A agents behind the *real* ``A2AServer`` routing layer,
wires them through the same ``AgentRuntime`` / ``Coordinator`` / ``Dispatcher``
code the live run uses, executes all 4 configurations twice, and asserts:

* every question x config produced a record;
* config semantics hold (single=1 call, all_agents=5 calls);
* multi_parallel really used the Coordinator and routed consistently;
* coverage/keyword improve for multi-source configs on cross_source questions;
* mock provenance is detected via ``data.source``;
* missing_source questions expose the spurious-result behaviour;
* re-running the same fake backend yields identical metrics (determinism).

Run::

    .venv/bin/python -m eval.selftest
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

from eval.client import AGENT_NAMES
from eval.metrics import CONFIGS
from eval.runner import (
    DEFAULT_QUESTIONS,
    load_questions,
    run_evaluation,
    write_outputs,
)
from src.agents.catalog import AGENT_SPECS, build_card
from src.orchestrator.registry import AgentRegistry
from src.orchestrator.router import Router
from src.protocol.models import AgentCard, Message, Part, Task
from src.protocol.server import A2AServer

ZERO_PACING = {name: 0.0 for name in AGENT_NAMES}


class FakeAgent(A2AServer):
    """A2AServer subclass with a deterministic, scripted response per query."""

    def __init__(self, name: str, card: AgentCard, behavior: dict[tuple[str, str], dict[str, Any]]):
        super().__init__(card=card)
        self.agent_name = name
        self._behavior = behavior

    async def handle_message(self, message: Message, task: Task) -> Message:
        text = ""
        for part in message.parts:
            if part.kind == "text" and part.text:
                text = part.text
                break
        spec = self._behavior.get(
            (self.agent_name, text), {"kind": "empty", "label": "no behavior"}
        )
        if spec["kind"] == "error":
            raise RuntimeError(spec.get("message", "fake agent failure"))
        if spec["kind"] == "weather":
            data = {
                "city": spec["city"],
                "temperature": 20,
                "humidity": 50,
                "condition": "clear sky",
            }
            return Message(
                role="agent",
                parts=[
                    Part(kind="text", text=f"Weather in {spec['city']}: 20°C, clear sky"),
                    Part(kind="data", data=data),
                ],
            )
        if spec["kind"] == "mock":
            data = {
                "source": "local-mock",
                "results": [{"title": spec["title"], "type": "Person", "birth": "1879-03-14"}],
            }
            return Message(
                role="agent",
                parts=[
                    Part(kind="text", text=f"Found knowledge about {spec['title']}（本地快照）"),
                    Part(kind="data", data=data),
                ],
            )
        if spec["kind"] == "real":
            results = spec.get("results", [])
            return Message(
                role="agent",
                parts=[
                    Part(kind="text", text=f"Found {len(results)} results"),
                    Part(kind="data", data={"results": results}),
                ],
            )
        # empty
        return Message(
            role="agent",
            parts=[
                Part(kind="text", text=spec.get("label", "未找到相关结果")),
                Part(kind="data", data={"results": []}),
            ],
        )


def _route(router: Router, query: str) -> list[str]:
    cards = router.rule_match(query)
    if not cards:
        cards = router.registry.get_enabled()[:3]
    return [card.name for card in cards]


def build_fake_instances(
    questions: list[dict[str, Any]],
) -> dict[str, FakeAgent]:
    registry = AgentRegistry()
    cards = {spec.name: build_card(spec) for spec in AGENT_SPECS}
    for name in AGENT_NAMES:
        registry.register_sync(cards[name])
    router = Router(registry=registry)

    behavior: dict[tuple[str, str], dict[str, Any]] = {}
    for question in questions:
        query = question["question"]
        expected = set(question.get("expected_agents") or [])
        keywords = question.get("expected_keywords") or {}
        _route(router, query)
        for agent in AGENT_NAMES:
            if agent in expected:
                keyword = keywords.get(agent, "result")
                if agent == "WikidataAgent":
                    behavior[(agent, query)] = {"kind": "mock", "title": f"{keyword} snapshot"}
                elif agent == "WeatherAgent":
                    behavior[(agent, query)] = {"kind": "weather", "city": keyword}
                else:
                    behavior[(agent, query)] = {
                        "kind": "real",
                        "results": [
                            {"title": f"{keyword} example result", "snippet": f"{keyword} content"},
                            {"title": f"{keyword} second result", "snippet": "more content"},
                        ],
                    }
            elif (
                question["category"] == "missing_source"
                and question["id"] == "ms-nobel-01"
                and agent == "WikipediaAgent"
            ):
                # Mirrors live behaviour: fallback routing returns plenty of
                # real-but-irrelevant Wikipedia data for an unanswerable query.
                behavior[(agent, query)] = {
                    "kind": "real",
                    "results": [{"title": "2026", "snippet": "2026 is a common year"}],
                }
            elif agent == "WeatherAgent":
                behavior[(agent, query)] = {
                    "kind": "error",
                    "message": "fake wttr.in 500 Internal Server Error",
                }
            elif agent == "WikidataAgent":
                behavior[(agent, query)] = {
                    "kind": "empty",
                    "label": "未找到与查询相关的知识图谱数据",
                }
            else:
                behavior[(agent, query)] = {"kind": "empty", "label": "Found 0 results"}

    instances: dict[str, FakeAgent] = {}
    for spec in AGENT_SPECS:
        instances[spec.name] = FakeAgent(spec.name, cards[spec.name], behavior)
    return instances


def _strip_timing(value: Any) -> Any:
    """Remove wall-clock fields so two fake runs must match exactly."""
    if isinstance(value, dict):
        return {
            key: _strip_timing(item)
            for key, item in value.items()
            if not any(marker in key for marker in ("latency", "elapsed", "duration"))
            and key not in {"generated_at", "run_id"}
        }
    if isinstance(value, list):
        return [_strip_timing(item) for item in value]
    return value


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  PASS  {message}")


async def _run(questions: list[dict[str, Any]]) -> dict[str, Any]:
    instances = build_fake_instances(questions)
    return await run_evaluation(
        questions,
        list(CONFIGS),
        agent_instances=instances,
        pacing=ZERO_PACING,
        preflight=False,
        progress_stream=None,
    )


async def main() -> int:
    questions, _ = load_questions(DEFAULT_QUESTIONS)
    print(
        f"selftest: {len(questions)} questions x {len(CONFIGS)} configs "
        "(fake backend, no network)"
    )
    report = await _run(questions)
    report2 = await _run(questions)

    configs = report["configs"]
    _assert(
        report["meta"]["rows"] == len(questions) * len(CONFIGS),
        "all question x config rows produced",
    )

    single = configs["single"]["overall"]
    multi = configs["multi_parallel"]["overall"]
    serial = configs["multi_serial"]["overall"]
    all_agents = configs["all_agents"]["overall"]
    _assert(single["agent_calls_avg"] == 1.0, "single always calls exactly one agent")
    _assert(all_agents["agent_calls_avg"] == 5.0, "all_agents always calls five agents")
    _assert(serial["agent_calls_avg"] >= single["agent_calls_avg"], "multi_serial calls >= single")
    _assert(multi["agent_calls_avg"] >= single["agent_calls_avg"], "multi_parallel calls >= single")

    consistency = [
        row["routing_consistent"]
        for row in configs["multi_parallel"]["per_question"]
    ]
    _assert(
        all(value is True for value in consistency),
        "multi_parallel routing matches rule_match",
    )

    cross_single = configs["single"]["by_category"]["cross_source"]["source_coverage"]
    cross_multi = configs["multi_parallel"]["by_category"]["cross_source"]["source_coverage"]
    _assert(cross_multi is not None and cross_single is not None and cross_multi > cross_single,
            "cross_source coverage improves for multi_parallel")
    _assert(multi["keyword_hit"] > single["keyword_hit"], "keyword_hit improves for multi_parallel")

    wd_total = {"mock": 0, "real": 0}
    for config in CONFIGS:
        wd = configs[config]["overall"]["source_status"]["per_agent"]["WikidataAgent"]
        wd_total["mock"] += wd["mock"]
        wd_total["real"] += wd["real"]
    # ss-wikidata (all 4 configs) + cs-wiki-wikidata (serial/parallel/all) are mock;
    # non-expected Wikidata calls return zero-result real responses.
    _assert(
        wd_total["mock"] == 7,
        "Wikidata mock detected via data.source (7 calls across configs)",
    )
    _assert(wd_total["real"] == 22, "Wikidata zero-result real responses kept separate from mock")
    ss_row = next(row for row in configs["multi_parallel"]["per_question"]
                  if row["question_id"] == "ss-wikidata-01")
    ss_wd = next(call for call in ss_row["calls"] if call["agent"] == "WikidataAgent")
    _assert(ss_wd["status"] == "mock" and ss_wd["keyword_hit"] is True
            and ss_wd["keyword_hit_real"] is False,
            "mock hit is counted in keyword_hit but excluded from keyword_hit_real")

    missing = configs["multi_parallel"]["overall"]["spurious_result_rate_missing_source"]
    _assert(missing == 0.25, "missing_source spurious rate matches scripted behavior (1/4)")

    weather = configs["multi_parallel"]["overall"]["source_status"]["per_agent"]["WeatherAgent"]
    _assert(weather["error"] >= 1, "ambiguous weather calls are classified as error")
    _assert(configs["multi_parallel"]["by_category"]["ambiguous"]["source_coverage"] == 1.0,
            "ambiguous: expected source still returns real result")

    _assert(_strip_timing(report["configs"]) == _strip_timing(report2["configs"]),
            "rerunning fake backend yields identical metrics (determinism)")

    out_dir = Path(tempfile.mkdtemp(prefix="eval-selftest-"))
    write_outputs(
        report,
        out_json=out_dir / "eval-selftest.json",
        out_md=out_dir / "eval-selftest.md",
        docs=None,
    )
    markdown = (out_dir / "eval-selftest.md").read_text(encoding="utf-8")
    _assert("## 2. 核心结果" in markdown and "## 6. 失败样本分析" in markdown,
            f"markdown report renders with all sections ({out_dir})")
    print(f"\nselftest OK — artifacts written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(__import__("asyncio").run(main()))
