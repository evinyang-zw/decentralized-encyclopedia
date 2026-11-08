"""Deterministic metric computation for the cross-domain evaluation harness.

No LLM judge is used anywhere: every number below is derived from
(a) which agents were routed/called, (b) the structured A2A ``Task`` returned
by each agent, (c) the agent's own ``source`` provenance marker and
(d) wall-clock latency. Given the same per-question run records this module is
a pure function, so reports are reproducible without re-running the network.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

CATEGORIES: tuple[str, ...] = ("single_source", "cross_source", "missing_source", "ambiguous")
CONFIGS: tuple[str, ...] = ("single", "multi_serial", "multi_parallel", "all_agents")

# Agents whose real answer is a single object rather than a results list are
# still counted as one returned result (WeatherAgent).
_STATUS_KEYS = ("real", "mock", "empty", "error")


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #
def percentile(values: Iterable[float], p: float) -> float | None:
    """Deterministic percentile (linear interpolation between ranks)."""
    data = sorted(float(v) for v in values if v is not None)
    if not data:
        return None
    if len(data) == 1:
        return round(data[0], 2)
    rank = (len(data) - 1) * (p / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return round(data[low], 2)
    weight = rank - low
    return round(data[low] * (1 - weight) + data[high] * weight, 2)


def mean(values: Iterable[float | None]) -> float | None:
    data = [float(v) for v in values if v is not None]
    if not data:
        return None
    return round(sum(data) / len(data), 4)


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


# --------------------------------------------------------------------------- #
# per-question metrics
# --------------------------------------------------------------------------- #
def question_metrics(run: dict[str, Any], question: dict[str, Any]) -> dict[str, Any]:
    """Compute coverage / keyword / effective / routing metrics for one run.

    Definitions (see docs/eval-report.md):
      source_coverage = fraction of ``expected_agents`` that returned a
                        non-empty *real* result (mock does not count).
      keyword_hit     = fraction of expected agents whose ``expected_keywords``
                        term appears in the returned content (any provenance).
      keyword_hit_real= same, but only for content from a real source.
      effective       = at least one expected agent returned a real result
                        (None for missing_source questions, which have no
                        expected agent by construction).
      spurious        = any called agent returned a real result on a
                        missing_source question (system did not abstain).
    """
    expected: list[str] = list(question.get("expected_agents") or [])
    keywords: dict[str, str] = dict(question.get("expected_keywords") or {})
    calls = {c["agent"]: c for c in run.get("calls", [])}
    called = list(run.get("called_agents") or [])

    hit_agents = [
        name for name in expected
        if calls.get(name, {}).get("has_real_result") is True
    ]
    coverage = ratio(len(hit_agents), len(expected)) if expected else None

    keyword_terms = {a: kw for a, kw in keywords.items() if kw}
    kw_hits = 0
    kw_hits_real = 0
    for agent, _kw in keyword_terms.items():
        call = calls.get(agent)
        if call is None:
            continue
        if call.get("keyword_hit") is True:
            kw_hits += 1
        if call.get("keyword_hit_real") is True:
            kw_hits_real += 1
    keyword_hit = ratio(kw_hits, len(keyword_terms)) if keyword_terms else None
    keyword_hit_real = ratio(kw_hits_real, len(keyword_terms)) if keyword_terms else None

    expected_set = set(expected)
    called_set = set(called)
    if expected:
        effective = bool(hit_agents)
        spurious = None
        routing_precision = (
            ratio(len(called_set & expected_set), len(called_set)) if called_set else None
        )
        routing_recall = ratio(len(called_set & expected_set), len(expected_set))
    else:
        effective = None
        spurious = any(c.get("has_real_result") is True for c in calls.values()) if calls else False
        routing_precision = None
        routing_recall = None

    return {
        "question_id": run["question_id"],
        "config": run["config"],
        "category": question["category"],
        "question": run["question"],
        "expected_agents": expected,
        "expected_keywords": keywords,
        "routed_agents": list(run.get("routed_agents") or []),
        "called_agents": called,
        "coverage": coverage,
        "keyword_hit": keyword_hit,
        "keyword_hit_real": keyword_hit_real,
        "effective": effective,
        "spurious_result": spurious,
        "routing_precision": routing_precision,
        "routing_recall": routing_recall,
        "agent_calls": len(called),
        "elapsed_ms": run["elapsed_ms"],
        "calls": run.get("calls", []),
        "answer": run.get("answer", ""),
        "process_log": run.get("process_log", []),
        "error": run.get("error"),
        "routing_consistent": run.get("routing_consistent"),
    }


# --------------------------------------------------------------------------- #
# source status
# --------------------------------------------------------------------------- #
def source_status(calls: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """real / mock / empty / error counts and ratios per agent and overall."""
    per_agent: dict[str, dict[str, Any]] = {}
    totals = {key: 0 for key in _STATUS_KEYS}
    for call in calls:
        agent = call["agent"]
        bucket = per_agent.setdefault(
            agent, {"calls": 0, **{key: 0 for key in _STATUS_KEYS}}
        )
        bucket["calls"] += 1
        status = call.get("status", "error")
        if status not in _STATUS_KEYS:
            status = "error"
        bucket[status] += 1
        totals[status] += 1

    def _with_ratios(bucket: dict[str, Any]) -> dict[str, Any]:
        total = bucket["calls"] or 1
        out = dict(bucket)
        out["ratios"] = {
            key: round(bucket[key] / total, 4) for key in _STATUS_KEYS
        }
        return out

    rendered = {agent: _with_ratios(bucket) for agent, bucket in sorted(per_agent.items())}
    overall = _with_ratios({"calls": sum(totals.values()), **totals})
    return {"per_agent": rendered, "overall": overall}


def per_agent_stats(calls: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Call-level latencies + keyword-hit rates per agent (all configs)."""
    buckets: dict[str, dict[str, Any]] = {}
    for call in calls:
        agent = call["agent"]
        bucket = buckets.setdefault(
            agent,
            {
                "calls": 0,
                "real": 0,
                "mock": 0,
                "empty": 0,
                "error": 0,
                "latencies": [],
                "keyword_calls": 0,
                "keyword_hits": 0,
                "keyword_hits_real": 0,
            },
        )
        bucket["calls"] += 1
        status = call.get("status", "error")
        if status in ("real", "mock", "empty", "error"):
            bucket[status] += 1
        if call.get("latency_ms") is not None:
            bucket["latencies"].append(call["latency_ms"])
        if call.get("keyword"):
            bucket["keyword_calls"] += 1
            if call.get("keyword_hit"):
                bucket["keyword_hits"] += 1
            if call.get("keyword_hit_real"):
                bucket["keyword_hits_real"] += 1

    rendered: dict[str, Any] = {}
    for agent, bucket in sorted(buckets.items()):
        rendered[agent] = {
            "calls": bucket["calls"],
            "real": bucket["real"],
            "mock": bucket["mock"],
            "empty": bucket["empty"],
            "error": bucket["error"],
            "success_rate": ratio(bucket["real"], bucket["calls"]),
            "latency_p50_ms": percentile(bucket["latencies"], 50),
            "latency_p95_ms": percentile(bucket["latencies"], 95),
            "keyword_calls": bucket["keyword_calls"],
            "keyword_hit_rate": ratio(bucket["keyword_hits"], bucket["keyword_calls"]),
            "keyword_hit_real_rate": ratio(bucket["keyword_hits_real"], bucket["keyword_calls"]),
        }
    return rendered


# --------------------------------------------------------------------------- #
# summaries
# --------------------------------------------------------------------------- #
def _summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in rows if r["expected_agents"]]
    missing = [r for r in rows if not r["expected_agents"]]
    coverage = mean(r["coverage"] for r in answerable)
    keyword_hit = mean(r["keyword_hit"] for r in answerable)
    keyword_hit_real = mean(r["keyword_hit_real"] for r in answerable)
    effective = mean(r["effective"] for r in answerable)
    latency_values = [r["elapsed_ms"] for r in rows]
    calls = [r["agent_calls"] for r in rows]
    routing_prec = mean(r["routing_precision"] for r in answerable)
    routing_rec = mean(r["routing_recall"] for r in answerable)
    spurious = mean(r["spurious_result"] for r in missing) if missing else None
    # Over *all* questions (missing_source counts as "no effective result"),
    # so this number is directly comparable to the literal metric wording.
    effective_all = ratio(
        sum(1 for r in rows if r["effective"] is True), len(rows)
    )
    all_calls = [call for r in rows for call in r["calls"]]
    return {
        "questions": len(rows),
        "answerable_questions": len(answerable),
        "missing_source_questions": len(missing),
        "source_coverage": coverage,
        "keyword_hit": keyword_hit,
        "keyword_hit_real": keyword_hit_real,
        "effective_rate": effective,
        "effective_rate_all_questions": effective_all,
        "spurious_result_rate_missing_source": spurious,
        "latency_p50_ms": percentile(latency_values, 50),
        "latency_p95_ms": percentile(latency_values, 95),
        "latency_mean_ms": mean(latency_values),
        "agent_calls_avg": mean(calls),
        "agent_calls_total": sum(calls),
        "routing_precision": routing_prec,
        "routing_recall": routing_rec,
        "source_status": source_status(all_calls),
        "per_agent": per_agent_stats(all_calls),
    }


def summarise_config(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Config-level summary + per-category breakdown."""
    summary = _summarise(rows)
    by_category: dict[str, Any] = {}
    for category in CATEGORIES:
        subset = [r for r in rows if r["category"] == category]
        if subset:
            by_category[category] = _summarise(subset)
    summary["by_category"] = by_category
    summary["per_question"] = [
        {
            key: row[key]
            for key in (
                "question_id", "category", "question", "expected_agents",
                "expected_keywords", "routed_agents", "called_agents",
                "coverage", "keyword_hit", "keyword_hit_real", "effective",
                "spurious_result", "routing_precision", "routing_recall",
                "agent_calls", "elapsed_ms", "answer", "calls", "error",
                "routing_consistent", "process_log",
            )
        }
        for row in rows
    ]
    return summary


def build_headline(configs: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Derive the resume-facing comparison numbers from real results."""
    def section(config: str) -> dict[str, Any]:
        return configs.get(config) or {"overall": {}, "by_category": {}}

    def get(config: str, metric: str) -> float | None:
        return section(config)["overall"].get(metric)

    section("single")["overall"]
    multi = section("multi_parallel")["overall"]
    section("multi_serial")["overall"]
    all_agents = section("all_agents")["overall"]

    def delta(new: float | None, old: float | None) -> float | None:
        if new is None or old is None:
            return None
        return round(new - old, 4)

    cross_single = section("single")["by_category"].get("cross_source", {})
    cross_multi = section("multi_parallel")["by_category"].get("cross_source", {})
    amb_single = section("single")["by_category"].get("ambiguous", {})
    amb_multi = section("multi_parallel")["by_category"].get("ambiguous", {})

    def latency_ratio(a: float | None, b: float | None) -> float | None:
        if not a or not b:
            return None
        return round(a / b, 2)

    return {
        "single_vs_multi_parallel": {
            "source_coverage_delta": delta(
                get("multi_parallel", "source_coverage"), get("single", "source_coverage")
            ),
            "keyword_hit_delta": delta(
                get("multi_parallel", "keyword_hit"), get("single", "keyword_hit")
            ),
            "effective_rate_delta": delta(
                get("multi_parallel", "effective_rate"), get("single", "effective_rate")
            ),
            "agent_calls_ratio": latency_ratio(
                get("multi_parallel", "agent_calls_avg"), get("single", "agent_calls_avg")
            ),
            "p95_latency_ratio": latency_ratio(
                get("multi_parallel", "latency_p95_ms"), get("single", "latency_p95_ms")
            ),
            "p50_latency_ratio": latency_ratio(
                get("multi_parallel", "latency_p50_ms"), get("single", "latency_p50_ms")
            ),
        },
        "cross_source": {
            "single_coverage": cross_single.get("source_coverage"),
            "multi_parallel_coverage": cross_multi.get("source_coverage"),
            "single_keyword_hit": cross_single.get("keyword_hit"),
            "multi_parallel_keyword_hit": cross_multi.get("keyword_hit"),
        },
        "ambiguous": {
            "single_coverage": amb_single.get("source_coverage"),
            "multi_parallel_coverage": amb_multi.get("source_coverage"),
            "single_calls": amb_single.get("agent_calls_avg"),
            "multi_parallel_calls": amb_multi.get("agent_calls_avg"),
            "single_precision": amb_single.get("routing_precision"),
            "multi_parallel_precision": amb_multi.get("routing_precision"),
        },
        "all_agents_vs_multi_parallel": {
            "coverage_delta": delta(
                get("all_agents", "source_coverage"), get("multi_parallel", "source_coverage")
            ),
            "keyword_hit_delta": delta(
                get("all_agents", "keyword_hit"), get("multi_parallel", "keyword_hit")
            ),
            "extra_calls_per_question": delta(
                get("all_agents", "agent_calls_avg"), get("multi_parallel", "agent_calls_avg")
            ),
            "p95_latency_ratio": latency_ratio(
                get("all_agents", "latency_p95_ms"), get("multi_parallel", "latency_p95_ms")
            ),
        },
        "serial_vs_parallel": {
            "p50_latency_ratio": latency_ratio(
                get("multi_serial", "latency_p50_ms"), get("multi_parallel", "latency_p50_ms")
            ),
            "p95_latency_ratio": latency_ratio(
                get("multi_serial", "latency_p95_ms"), get("multi_parallel", "latency_p95_ms")
            ),
            "coverage_delta": delta(
                get("multi_serial", "source_coverage"), get("multi_parallel", "source_coverage")
            ),
        },
        "missing_source": {
            "single_spurious_rate": get("single", "spurious_result_rate_missing_source"),
            "multi_parallel_spurious_rate": multi.get("spurious_result_rate_missing_source"),
            "all_agents_spurious_rate": all_agents.get("spurious_result_rate_missing_source"),
        },
    }


def build_report(
    meta: dict[str, Any],
    rows: list[dict[str, Any]],
    questions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the JSON payload written to reports/eval-latest.json."""
    configs: dict[str, Any] = {}
    for config in CONFIGS:
        subset = [r for r in rows if r["config"] == config]
        if not subset:
            continue
        summary = summarise_config(subset)
        configs[config] = {
            "overall": {
                key: value
                for key, value in summary.items()
                if key not in ("per_question", "by_category")
            },
            "by_category": summary["by_category"],
            "per_question": summary["per_question"],
        }

    headline = build_headline(
        {name: {"overall": payload["overall"], "by_category": payload["by_category"]}
         for name, payload in configs.items()},
        questions,
    )
    return {
        "schema": "eval-report/v1",
        "meta": meta,
        "headline": headline,
        "questions": [questions[qid] for qid in questions],
        "configs": configs,
    }
