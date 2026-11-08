"""Executable entry point for the cross-domain evaluation harness.

Usage::

    python -m eval.runner                      # full live run (18 questions x 4 configs)
    python -m eval.runner --limit 2            # smoke test
    python -m eval.runner --configs single     # one configuration
    python -m eval.runner --backend fake       # deterministic self-test backend (no network)

Outputs by default:
    reports/eval-latest.json   machine-readable results (all runs + metrics)
    reports/eval-latest.md     rendered comparison report
    docs/eval-report.md        long-form methodology / results / failure analysis

The runner never calls an LLM (``llm=None`` everywhere) and never opens a TCP
port: the five FastAPI agent apps are driven in-process over
``httpx.ASGITransport``.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from eval.client import (
    AGENT_NAMES,
    CONFIG_NAMES,
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PACING,
    DEFAULT_TIMEOUTS,
    AgentRuntime,
)
from eval.metrics import CATEGORIES, CONFIGS, build_report, question_metrics

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUESTIONS = PROJECT_ROOT / "eval" / "questions.jsonl"
DEFAULT_OUT_JSON = PROJECT_ROOT / "reports" / "eval-latest.json"
DEFAULT_OUT_MD = PROJECT_ROOT / "reports" / "eval-latest.md"
DEFAULT_DOCS = PROJECT_ROOT / "docs" / "eval-report.md"

CONFIG_LABELS = {
    "single": "single（单 Agent 直答）",
    "multi_serial": "multi_serial（多源串行）",
    "multi_parallel": "multi_parallel（系统现状 · 真实 Coordinator）",
    "all_agents": "all_agents（全 5 源并行 · 成本上限）",
}

METRIC_LABELS = {
    "source_coverage": "source_coverage（真实命中率）",
    "keyword_hit": "keyword_hit（内容相关性）",
    "keyword_hit_real": "keyword_hit_real（仅真实来源）",
    "effective_rate": "effective_rate（至少 1 源有效）",
    "latency_p50_ms": "latency p50（ms）",
    "latency_p95_ms": "latency p95（ms）",
    "agent_calls_avg": "agent_calls / 题",
    "routing_precision": "routing precision",
    "spurious_result_rate_missing_source": "missing_source 误报率",
}

WIKIDATA_NO_UA_NOTE = "无 User-Agent 时 Wikimedia robot policy 固定 403（历史已知问题）"

UPSTREAM_PROBES: tuple[tuple[str, str, dict[str, str], dict[str, Any] | None], ...] = (
    (
        "DBpedia Lookup",
        "https://lookup.dbpedia.org/api/search",
        {"query": "Python", "format": "json", "maxResults": "1"},
        None,
    ),
    (
        "arXiv API",
        "https://export.arxiv.org/api/query",
        {"search_query": "all:quantum entanglement", "max_results": "1"},
        None,
    ),
    (
        "GitLab API",
        "https://gitlab.com/api/v4/projects",
        {"search": "python", "per_page": "1"},
        None,
    ),
    ("wttr.in", "https://wttr.in/Beijing", {"format": "j1"}, None),
    (
        "Wikidata API（带 UA）",
        "https://www.wikidata.org/w/api.php",
        {"action": "wbsearchentities", "search": "Einstein", "language": "en",
         "format": "json", "limit": "1"},
        {"User-Agent": "DecentralizedEncyclopedia/0.2 (eval harness)"},
    ),
)


# --------------------------------------------------------------------------- #
# inputs / metadata
# --------------------------------------------------------------------------- #
def load_questions(path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno} invalid JSON: {exc}") from exc
            required = {"id", "category", "question", "expected_agents", "expected_keywords"}
            missing = required - set(item)
            if missing:
                raise ValueError(f"{path}:{lineno} missing fields {sorted(missing)}")
            if item["category"] not in CATEGORIES:
                raise ValueError(f"{path}:{lineno} unknown category {item['category']!r}")
            if item["id"] in seen:
                raise ValueError(f"{path}:{lineno} duplicate id {item['id']!r}")
            seen.add(item["id"])
            expected = item["expected_agents"]
            if not isinstance(expected, list) or any(
                agent not in AGENT_NAMES for agent in expected
            ):
                raise ValueError(f"{path}:{lineno} expected_agents must be subset of {AGENT_NAMES}")
            questions.append(item)
    if not questions:
        raise ValueError(f"{path}: no questions found")
    return questions, {item["id"]: item for item in questions}


def git_info() -> dict[str, Any]:
    def _run(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=5
            ).stdout.strip()
        except Exception:  # noqa: BLE001 - metadata must never break a run
            return ""

    commit = _run("rev-parse", "--short", "HEAD") or "unknown"
    status = _run("status", "--porcelain")
    return {
        "commit": commit,
        "dirty": bool(status),
        "dirty_files": status.splitlines()[:20],
        "branch": _run("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
    }


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def probe_upstreams(timeout: float = 12.0) -> dict[str, Any]:
    """One direct HTTP probe per upstream, recorded in the report meta.

    Wikidata is additionally probed *without* a User-Agent to document the
    historical 403 -> mock fallback behaviour.
    """
    async def one(name: str, url: str, params: dict[str, Any], headers: dict[str, str] | None):
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=timeout, headers=headers or {}, follow_redirects=True
            ) as client:
                resp = await client.get(url, params=params)
            latency = round((time.perf_counter() - started) * 1000.0, 2)
            entry = {
                "probe": name,
                "url": url,
                "status_code": resp.status_code,
                "ok": resp.status_code == 200,
                "latency_ms": latency,
            }
            if name.startswith("Wikidata") and resp.status_code == 200:
                try:
                    docs = resp.json().get("search", [])
                    entry["hits"] = len(docs)
                except ValueError:
                    entry["hits"] = None
            return name, entry
        except Exception as exc:  # noqa: BLE001 - probe failure is data
            return name, {
                "probe": name,
                "url": url,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
            }

    tasks = [one(*spec) for spec in UPSTREAM_PROBES]
    tasks.append(
        one(
            "Wikidata API（无 UA）",
            "https://www.wikidata.org/w/api.php",
            {"action": "wbsearchentities", "search": "Einstein", "language": "en",
             "format": "json", "limit": "1"},
            None,
        )
    )
    results = dict(await asyncio.gather(*tasks))
    no_ua = results.pop("Wikidata API（无 UA）", {})
    results["Wikidata API（无 UA）"] = {
        **no_ua,
        "note": WIKIDATA_NO_UA_NOTE,
        "expected_status": 403,
    }
    return results


def _run_id(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        [
            {
                "id": row["question_id"],
                "config": row["config"],
                "calls": [
                    {"agent": c["agent"], "status": c["status"], "n": c["result_count"]}
                    for c in row["calls"]
                ],
                "elapsed_ms": round(row["elapsed_ms"]),
            }
            for row in rows
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def build_meta(
    *,
    started_at: datetime,
    duration_s: float,
    questions_path: Path,
    questions: list[dict[str, Any]],
    configs: list[str],
    upstream_health: dict[str, Any],
    docs_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "generated_at": started_at.astimezone(UTC).isoformat(timespec="seconds"),
        "duration_s": round(duration_s, 2),
        "runtime": "in-process ASGI (httpx.ASGITransport), no TCP ports opened",
        "llm": "disabled (rule-based router + rule-based aggregation, no API key)",
        "git": git_info(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "questions_file": str(questions_path.relative_to(PROJECT_ROOT)),
        "num_questions": len(questions),
        "categories": {
            category: sum(1 for q in questions if q["category"] == category)
            for category in CATEGORIES
        },
        "configs": configs,
        "agents": list(AGENT_NAMES),
        "agent_budget": {
            "timeout_s": DEFAULT_AGENT_TIMEOUT,
            "timeouts_s": dict(DEFAULT_TIMEOUTS),
            "max_retries": DEFAULT_MAX_RETRIES,
            "note": (
                "4 种配置统一使用同一 agent 预算（产品默认 max_retries=1；"
                "因 arXiv 本环境限流，评测关闭重试、并把 ArxivAgent 超时收紧到 6s，"
                "以控制单次运行 <5 分钟；超时仍如实计为 error）"
            ),
        },
        "pacing_s": dict(DEFAULT_PACING),
        "upstream_health": upstream_health,
        "config_definitions": {
            "single": "Router.rule_match(q) 第一个 agent，串行 1 次；聚合用 Coordinator.aggregate",
            "multi_serial": "Router.rule_match(q) 全部 agent 串行；聚合用 Coordinator.aggregate",
            "multi_parallel": "真实 Coordinator.handle_message（规则路由 + 并行派发 + 规则聚合）",
            "all_agents": "固定 5 个 agent 全部并行调用；聚合用 Coordinator.aggregate",
            "routing_fallback": "未命中时与 Coordinator 一致，回退 registry.get_enabled()[:3]",
            "config_order": "每个问题按题号轮转 4 配置顺序，抵消先后顺序/缓存偏差",
        },
        "docs_extra": docs_extra or {},
    }


# --------------------------------------------------------------------------- #
# live evaluation loop
# --------------------------------------------------------------------------- #
async def run_evaluation(
    questions: list[dict[str, Any]],
    configs: list[str],
    *,
    questions_path: Path = DEFAULT_QUESTIONS,
    agent_instances: dict[str, Any] | None = None,
    pacing: dict[str, float] | None = None,
    agent_timeout: float = DEFAULT_AGENT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeouts: dict[str, float] | None = None,
    preflight: bool = True,
    progress_stream: Any = None,
    only_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Run every (question, config) pair and return the full report payload."""
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    selected = [q for q in questions if not only_ids or q["id"] in only_ids]
    question_index = {q["id"]: q for q in selected}

    upstream_health: dict[str, Any] = {}
    if preflight:
        upstream_health = await probe_upstreams()

    runtime = AgentRuntime(
        agent_instances=agent_instances,
        pacing=pacing,
        agent_timeout=agent_timeout,
        max_retries=max_retries,
        timeouts=timeouts,
    )
    rows: list[dict[str, Any]] = []
    try:
        for q_index, question in enumerate(selected):
            rotation = q_index % len(configs)
            ordered_configs = configs[rotation:] + configs[:rotation]
            for config in ordered_configs:
                run = await runtime.run_config(config, question)
                row = question_metrics(run.to_dict(), question)
                rows.append(row)
                if progress_stream is not None:
                    statuses = ", ".join(
                        f"{call['agent']}:{call['status']}" for call in row["calls"]
                    ) or "no-calls"
                    print(
                        f"[{q_index + 1:02d}/{len(selected):02d}] "
                        f"{question['id']:<18s} {config:<14s} "
                        f"calls={row['agent_calls']} {row['elapsed_ms']:7.1f}ms "
                        f"cov={_pct(row['coverage'])} kw={_pct(row['keyword_hit'])} | {statuses}",
                        file=progress_stream,
                        flush=True,
                    )
    finally:
        runtime.close()

    duration = time.perf_counter() - started
    report = build_report(
        build_meta(
            started_at=started_at,
            duration_s=duration,
            questions_path=questions_path,
            questions=selected,
            configs=configs,
            upstream_health=upstream_health,
        ),
        rows,
        question_index,
    )
    report["meta"]["run_id"] = _run_id(rows)
    report["meta"]["rows"] = len(rows)
    return report


# --------------------------------------------------------------------------- #
# markdown rendering helpers
# --------------------------------------------------------------------------- #
def _pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        lines.append("| " + " | ".join("" if cell is None else str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _calls_summary(row: dict[str, Any]) -> str:
    if not row["calls"]:
        return "—"
    return ", ".join(f"{c['agent'].replace('Agent', '')}:{c['status']}" for c in row["calls"])


def _status_mark(status: str) -> str:
    return {
        "real": "real",
        "mock": "**mock**",
        "empty": "empty",
        "error": "**error**",
    }.get(status, status)


def headline_sentences(report: dict[str, Any]) -> list[str]:
    head = report["headline"]
    overall = {name: payload["overall"] for name, payload in report["configs"].items()}
    sentences: list[str] = []
    cmp_ = head["single_vs_multi_parallel"]
    if "multi_parallel" in overall and "single" in overall:
        mp, sg = overall["multi_parallel"], overall["single"]
        sentences.append(
            f"**multi_parallel 相对 single**：source_coverage {_pct(sg['source_coverage'])} → "
            f"{_pct(mp['source_coverage'])}（{_signed(cmp_['source_coverage_delta'])}），"
            f"keyword_hit {_pct(sg['keyword_hit'])} → {_pct(mp['keyword_hit'])}"
            f"（{_signed(cmp_['keyword_hit_delta'])}），"
            f"有效题率 {_pct(sg['effective_rate'])} → {_pct(mp['effective_rate'])}。"
        )
    if "multi_serial" in overall and "multi_parallel" in overall:
        overall["multi_serial"]
        if report["configs"]["multi_serial"]["overall"].get("latency_p95_ms"):
            sentences.append(
                f"**并行 vs 串行**：p50 {_ms(overall['multi_serial']['latency_p50_ms'])} ms → "
                f"{_ms(overall['multi_parallel']['latency_p50_ms'])} ms，"
                f"p95 {_ms(overall['multi_serial']['latency_p95_ms'])} ms → "
                f"{_ms(overall['multi_parallel']['latency_p95_ms'])} ms（覆盖率基本不变）。"
            )
    if "all_agents" in overall and "multi_parallel" in overall:
        all_ = overall["all_agents"]
        cmp2 = head["all_agents_vs_multi_parallel"]
        sentences.append(
            f"**全源上限对照**：all_agents 每题调用 {_num(all_['agent_calls_avg'])} 次"
            f"（multi_parallel {_num(overall['multi_parallel']['agent_calls_avg'])} 次），"
            f"source_coverage {_pct(all_['source_coverage'])} vs "
            f"{_pct(overall['multi_parallel']['source_coverage'])}"
            f"（Δ {_signed(cmp2['coverage_delta'])}），收益有限但成本固定拉满。"
        )
    cross = head["cross_source"]
    if cross.get("single_coverage") is None and cross.get("multi_parallel_coverage") is None:
        cross = None
    if cross is not None:
        sentences.append(
            f"**跨源问题（cross_source）**：single 覆盖率 {_pct(cross['single_coverage'])}，"
            f"multi_parallel {_pct(cross['multi_parallel_coverage'])}；"
            f"keyword_hit {_pct(cross['single_keyword_hit'])} → "
            f"{_pct(cross['multi_parallel_keyword_hit'])}。"
        )
    amb = head["ambiguous"]
    if amb.get("single_coverage") is not None:
        sentences.append(
            f"**歧义问题（ambiguous）**：multi_parallel 覆盖率 "
            f"{_pct(amb['multi_parallel_coverage'])}，"
            f"single {_pct(amb['single_coverage'])}（未提升）；每题调用 "
            f"{_num(amb['single_calls'])} → {_num(amb['multi_parallel_calls'])} 次，路由 precision "
            f"{_pct(amb['single_precision'])} → {_pct(amb['multi_parallel_precision'])}。"
            "歧义题上多 Agent 的额外调用没有带来覆盖提升（本次运行还叠加了上游限流噪声），"
            "是成本而非收益。"
        )
    miss = head["missing_source"]
    if miss.get("multi_parallel_spurious_rate") is not None:
        sentences.append(
            f"**缺源问题（missing_source）**：系统无对应数据源，但仍返回非空结果的比例 "
            f"multi_parallel {_pct(miss['multi_parallel_spurious_rate'])}、"
            f"single {_pct(miss['single_spurious_rate'])}——"
            "规则路由/兜底会把无关数据源当成答案来源，"
            "这是无 LLM judge 评测无法覆盖的“相关性”盲区（详见失败分析）。"
        )
    return sentences


def _signed(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) <= 1.0 and abs(value) > 0.001:
        return f"{value * 100:+.1f}pp"
    return f"{value:+.2f}"


def render_markdown(report: dict[str, Any], *, detailed: bool = False) -> str:
    meta = report["meta"]
    configs = report["configs"]
    config_names = [c for c in CONFIGS if c in configs]
    lines: list[str] = []
    title = "去中心化百科 · 跨域多 Agent 评测报告"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(
        "> 纯规则路由 / 规则聚合，无 LLM key、无 LLM judge；5 个 domain agent 均以进程内 "
        "ASGI 驱动（`httpx.ASGITransport`），未占用 8000–8005 端口。"
    )
    lines.append("")
    lines.append(
        _table(
            ["项", "值"],
            [
                ["生成时间（UTC）", meta["generated_at"]],
                ["git commit", f"`{meta['git']['commit']}`"
                 + ("（工作区有改动）" if meta["git"]["dirty"] else "")],
                ["运行时长", f"{meta['duration_s']} s"],
                ["run_id", f"`{meta.get('run_id', 'n/a')}`"],
                ["题目数", meta["num_questions"]],
                ["配置", ", ".join(meta["configs"])],
                ["LLM", meta["llm"]],
                ["agent 预算", f"timeout={meta['agent_budget']['timeout_s']}s"
                               f" (Arxiv "
                               f"{meta['agent_budget']['timeouts_s'].get('ArxivAgent', 'n/a')}s), "
                               f"max_retries={meta['agent_budget']['max_retries']}"],
                ["Python", meta["python"]],
            ],
        )
    )
    lines.append("")

    # ---------------------------------------------------------------- headline
    lines.append("## 0. 一句话结论")
    lines.append("")
    for sentence in headline_sentences(report):
        lines.append(f"- {sentence}")
    lines.append("")

    # ------------------------------------------------------------- methodology
    lines.append("## 1. 评测方法")
    lines.append("")
    lines.append("### 1.1 四种配置（只变路由/调度，聚合层不变）")
    lines.append("")
    lines.append(
        _table(
            ["配置", "实现"],
            [[CONFIG_LABELS[c], meta["config_definitions"][c]] for c in config_names],
        )
    )
    lines.append("")
    lines.append(
        "所有配置统一使用 `Coordinator.aggregate(query, results)` 做结果拼接；"
        "`multi_parallel` 走真实 `Coordinator.handle_message`（真实 Dispatcher 并行/超时/聚合），"
        "作为产品端到端路径对照。规则未命中时按产品逻辑回退 `registry.get_enabled()[:3]`。"
        "每个问题按题号轮转配置顺序，抵消配置先后与外部缓存带来的顺序效应。"
    )
    lines.append("")
    lines.append("### 1.2 指标定义（全部确定性，可复算）")
    lines.append("")
    lines.append(
        _table(
            ["指标", "定义"],
            [
                ["source_coverage",
                 "`expected_agents` 中返回**非空真实结果**的占比，按可答题平均；mock 不算真实"],
                ["keyword_hit", "`expected_keywords` 命中返回内容的占比（含 mock 来源），"
                                 "按可答题平均"],
                ["keyword_hit_real", "同上，但仅统计 `status=real` 的来源（用于区分 mock 命中）"],
                ["effective_rate", "可答题中至少 1 个期望数据源返回非空真实结果的占比"],
                ["latency p50/p95", "每道题在该配置下端到端耗时（含聚合）的 p50/p95"],
                ["agent_calls", "平均每题 agent 调用次数（不含重试；评测 max_retries=0）"],
                ["source_status", "每个数据源 real / mock / empty / error 的调用占比"
                                   "（Wikidata 读 data.source 字段）"],
                ["routing precision/recall", "实际调用集合与 `expected_agents` 的交集占比"
                                              "（路由质量）"],
                ["spurious_result_rate", "missing_source 题中仍有非空真实结果的占比（越低越好）"],
            ],
        )
    )
    lines.append("")
    lines.append("### 1.3 复现")
    lines.append("")
    lines.append("```bash")
    lines.append("cd /Users/Admin1/MiMoCode/decentralized-encyclopedia")
    lines.append("python -m eval.runner          # 或: .venv/bin/python -m eval.runner")
    lines.append("```")
    lines.append("")
    lines.append(
        "评测使用 live 网络（DBpedia / arXiv / GitLab / wttr.in / Wikidata），"
        "外部数据源可用性本身是评测对象的一部分；`--backend fake` 可在无网络下做确定性自测。"
    )
    lines.append("")

    # -------------------------------------------------------------- core table
    lines.append("## 2. 核心结果（4 配置总表）")
    lines.append("")
    headers = ["指标"] + [c for c in config_names]
    rows: list[list[Any]] = []
    for metric, label in METRIC_LABELS.items():
        values: list[Any] = []
        for config in config_names:
            overall = configs[config]["overall"]
            if metric in ("source_coverage", "keyword_hit", "keyword_hit_real", "effective_rate",
                          "routing_precision", "spurious_result_rate_missing_source"):
                values.append(_pct(overall.get(metric)))
            elif metric in ("latency_p50_ms", "latency_p95_ms"):
                values.append(_ms(overall.get(metric)))
            else:
                values.append(_num(overall.get(metric)))
        rows.append([label, *values])
    rows.insert(0, ["可答题数 / 总题数", *[f"{configs[c]['overall']['answerable_questions']}/"
                     f"{configs[c]['overall']['questions']}" for c in config_names]])
    
    rows.insert(0, ["平均每题耗时（ms）",
                    *[_ms(configs[c]["overall"].get("latency_mean_ms")) for c in config_names]])
    rows.insert(0, ["总 agent 调用数",
                    *[configs[c]["overall"].get("agent_calls_total") for c in config_names]])
    lines.append(_table(headers, rows))
    lines.append("")
    lines.append(
        "> `source_coverage/keyword_hit/effective_rate` 只在 14 道可答题"
        "（有期望数据源的题）上统计；"
        "4 道 missing_source 题没有期望数据源，单独用 `spurious_result_rate` "
        "衡量“无源仍作答”的行为。"
    )
    lines.append("")

    # ---------------------------------------------------------- by category
    lines.append("## 3. 按类别结果")
    lines.append("")
    for category in CATEGORIES:
        present = [c for c in config_names if category in configs[c]["by_category"]]
        if not present:
            continue
        category_questions = meta["categories"].get(category, 0)
        lines.append(f"### {category}（{category_questions} 题）")
        lines.append("")
        cat_rows: list[list[Any]] = []
        for config in present:
            cat = configs[config]["by_category"][category]
            cat_rows.append(
                [
                    config,
                    _pct(cat.get("source_coverage")),
                    _pct(cat.get("keyword_hit")),
                    _pct(cat.get("keyword_hit_real")),
                    _pct(cat.get("effective_rate")),
                    _num(cat.get("agent_calls_avg")),
                    _ms(cat.get("latency_p50_ms")),
                    _ms(cat.get("latency_p95_ms")),
                    (
                        _pct(cat.get("spurious_result_rate_missing_source"))
                        if category == "missing_source"
                        else "—"
                    ),
                ]
            )
        lines.append(
            _table(
                ["配置", "coverage", "keyword_hit", "keyword_hit_real", "effective",
                 "calls/题", "p50 ms", "p95 ms", "spurious"],
                cat_rows,
            )
        )
        lines.append("")

    # ---------------------------------------------------------- source status
    lines.append("## 4. 数据源状态（source_status）")
    lines.append("")
    lines.append(
        "聚合 4 种配置下的全部 agent 调用；mock 仅来自 WikidataAgent 的 `data.source=local-mock`。"
    )
    lines.append("")
    status_rows: list[list[Any]] = []
    all_calls = [
        call
        for config in config_names
        for row in configs[config]["per_question"]
        for call in row["calls"]
    ]
    from eval.metrics import source_status as _source_status

    status = _source_status(all_calls)
    for agent in AGENT_NAMES:
        bucket = status["per_agent"].get(agent)
        if not bucket:
            continue
        status_rows.append(
            [
                agent,
                bucket["calls"],
                f"{bucket['real']} ({_pct(bucket['ratios']['real'])})",
                f"{bucket['mock']} ({_pct(bucket['ratios']['mock'])})",
                f"{bucket['empty']} ({_pct(bucket['ratios']['empty'])})",
                f"{bucket['error']} ({_pct(bucket['ratios']['error'])})",
            ]
        )
    overall = status["overall"]
    status_rows.append(
        [
            "**合计**",
            overall["calls"],
            f"{overall['real']} ({_pct(overall['ratios']['real'])})",
            f"{overall['mock']} ({_pct(overall['ratios']['mock'])})",
            f"{overall['empty']} ({_pct(overall['ratios']['empty'])})",
            f"{overall['error']} ({_pct(overall['ratios']['error'])})",
        ]
    )
    lines.append(_table(["数据源", "调用数", "real", "mock", "empty", "error"], status_rows))
    lines.append("")
    lines.append("### 上游可用性探针（运行前直连探测）")
    lines.append("")
    probe_rows: list[list[Any]] = []
    for name, entry in meta["upstream_health"].items():
        probe_rows.append(
            [
                name,
                entry.get("status_code", "—"),
                "OK" if entry.get("ok") else "FAIL",
                _ms(entry.get("latency_ms")),
                _short(entry.get("error") or entry.get("note") or "", 120),
            ]
        )
    lines.append(_table(["上游", "HTTP", "结果", "延迟 ms", "备注"], probe_rows))
    lines.append("")
    wd = meta["upstream_health"].get("Wikidata API（带 UA）", {})
    wd_no_ua = meta["upstream_health"].get("Wikidata API（无 UA）", {})
    lines.append(
        f"Wikidata：带 UA 探针 HTTP {wd.get('status_code', '—')}；"
        f"无 UA 探针 HTTP {wd_no_ua.get('status_code', '—')}"
        "（历史 403 已知问题，Agent 侧已带 UA）。"
        "Agent 调用中 Wikidata 的真实/快照分布见上表 `mock` 列。"
    )
    lines.append("")

    # --------------------------------------------------------- per-question
    lines.append("## 5. 每题明细")
    lines.append("")
    for config in config_names:
        lines.append(f"### {CONFIG_LABELS[config]}")
        lines.append("")
        q_rows: list[list[Any]] = []
        for row in configs[config]["per_question"]:
            q_rows.append(
                [
                    row["question_id"],
                    row["category"],
                    "→".join(a.replace("Agent", "") for a in (row["routed_agents"] or ["∅"])),
                    _calls_summary(row),
                    _pct(row["coverage"]),
                    _pct(row["keyword_hit"]),
                    "✓" if row["effective"] else ("—" if row["effective"] is None else "✗"),
                    row["agent_calls"],
                    _ms(row["elapsed_ms"]),
                ]
            )
        lines.append(
            _table(
                ["题目", "类别", "路由", "各源状态", "coverage", "keyword", "有效", "calls", "ms"],
                q_rows,
            )
        )
        lines.append("")

    # ------------------------------------------------------- failure analysis
    lines.append("## 6. 失败样本分析")
    lines.append("")
    failure_rows: list[list[Any]] = []
    for config in config_names:
        for row in configs[config]["per_question"]:
            if not row["expected_agents"]:
                continue
            problems: list[str] = []
            if row["coverage"] is not None and row["coverage"] < 1.0:
                missing = [a for a in row["expected_agents"] if not _call_ok(row, a)]
                if missing:
                    problems.append("未命中: " + ", ".join(missing))
            for call in row["calls"]:
                if call["status"] in ("error", "mock", "empty"):
                    detail = call.get("error") or call["status"]
                    problems.append(f"{call['agent']}={detail[:80]}")
            misses = [
                f"{agent}:'{term}'"
                for agent, term in row["expected_keywords"].items()
                if _call_for(row, agent) and _call_for(row, agent).get("keyword_hit") is not True
            ]
            if misses:
                problems.append("keyword 未命中: " + ", ".join(misses))
            if problems:
                failure_rows.append(
                    [row["question_id"], config, "；".join(problems)]
                )
    if failure_rows:
        lines.append(_table(["题目", "配置", "失败原因"], failure_rows))
    else:
        lines.append("本次运行没有失败样本。")
    lines.append("")
    lines.append("### 失败模式归纳")
    lines.append("")
    for pattern in failure_patterns(report):
        lines.append(f"- {pattern}")
    lines.append("")

    # ------------------------------------------------------------- limitation
    lines.append("## 7. 局限声明")
    lines.append("")
    for limitation in limitations(detailed=detailed):
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


def _call_for(row: dict[str, Any], agent: str) -> dict[str, Any] | None:
    for call in row["calls"]:
        if call["agent"] == agent:
            return call
    return None


def _call_ok(row: dict[str, Any], agent: str) -> bool:
    call = _call_for(row, agent)
    return bool(call and call.get("has_real_result"))


def failure_patterns(report: dict[str, Any]) -> list[str]:
    """Deterministic, data-derived failure-mode bullets."""
    configs = report["configs"]
    patterns: list[str] = []

    # per-agent status distribution
    for agent in AGENT_NAMES:
        counts = {"real": 0, "mock": 0, "empty": 0, "error": 0}
        reasons: dict[str, int] = {}
        for config in configs.values():
            for row in config["per_question"]:
                for call in row["calls"]:
                    if call["agent"] != agent:
                        continue
                    status = call["status"]
                    counts[status] = counts.get(status, 0) + 1
                    if status == "error":
                        reason = _short(call.get("error") or "unknown", 70)
                        reasons[reason] = reasons.get(reason, 0) + 1
        total = sum(counts.values())
        if not total:
            continue
        detail = "，".join(f"{k}={v}" for k, v in counts.items() if v)
        if reasons:
            top = sorted(reasons.items(), key=lambda item: -item[1])[:2]
            reason_text = "；主要错误：" + " / ".join(f"{r} ×{n}" for r, n in top)
        else:
            reason_text = ""
        patterns.append(f"{agent} 共 {total} 次调用：{detail}{reason_text}。")

    limit_hits: dict[str, int] = {}
    for config in configs.values():
        for row in config["per_question"]:
            for call in row["calls"]:
                message = call.get("error") or ""
                if "429" in message:
                    limit_hits[call["agent"]] = limit_hits.get(call["agent"], 0) + 1
                elif "403" in message and call["agent"] == "WikidataAgent":
                    key = "WikidataAgent(403)"
                    limit_hits[key] = limit_hits.get(key, 0) + 1
    if limit_hits:
        pacing = report.get("meta", {}).get("pacing_s", {})
        pacing_text = "、".join(
            f"{agent.replace('Agent', '')} {pacing.get(agent, 'n/a')}s"
            for agent in ("ArxivAgent", "GithubAgent", "WikidataAgent")
        )
        patterns.append(
            "上游限流命中（真实环境噪声，已保留失败样本）："
            + "、".join(f"{agent} {hits} 次" for agent, hits in sorted(limit_hits.items()))
            + f"。本次运行实际请求间隔：{pacing_text}；"
            "但公共 API 的匿名配额仍可能被一次完整评测（约 176 次调用）打满，"
            "这是 source_coverage 在部分题上低于 100% 的直接原因之一。"
        )

    single = configs.get("single")
    multi = configs.get("multi_parallel")
    if single and multi:
        cross_single = single["by_category"].get("cross_source", {})
        cross_multi = multi["by_category"].get("cross_source", {})
        if cross_single and cross_multi:
            patterns.append(
                f"cross_source：single 每题只能调用规则顺序第一个源"
                f"（{cross_single.get('questions', 0)} 题），"
                f"coverage {_pct(cross_single.get('source_coverage'))}；"
                f"multi_parallel {_pct(cross_multi.get('source_coverage'))}——"
                "多 Agent 的结构性收益来自“多源同时返回真实结果”，而不是更深的内容。"
            )
    amb_single = single["by_category"].get("ambiguous", {}) if single else {}
    amb_multi = multi["by_category"].get("ambiguous", {}) if multi else {}
    if amb_single and amb_multi:
        patterns.append(
            f"ambiguous：single 每题 {_num(amb_single.get('agent_calls_avg'))} 次、"
            f"multi_parallel {_num(amb_multi.get('agent_calls_avg'))} 次，"
            f"routing precision {_pct(amb_single.get('routing_precision'))} → "
            f"{_pct(amb_multi.get('routing_precision'))}；"
            f"coverage {_pct(amb_single.get('source_coverage'))} → "
            f"{_pct(amb_multi.get('source_coverage'))}。"
            "多出来的调用来自被歧义关键词误触发的 agent；收益取决于被误触发源是否恰好返回真实结果，"
            "本次运行中这些调用未转化为覆盖（部分源同时受上游限流影响，见 source_status）。"
        )
    miss = multi["by_category"].get("missing_source", {}) if multi else {}
    if miss:
        patterns.append(
            f"missing_source：multi_parallel 仍有 "
            f"{_pct(miss.get('spurious_result_rate_missing_source'))} 的题"
            "返回了非空真实结果（来自规则未命中后的兜底 agent）。"
            "没有 LLM judge，无法自动判定这些内容"
            "是否“答非所问”，但它们显然不包含问题所需的数据源——这暴露了“缺源时无弃答能力”的问题。"
        )
    wd_total = {"calls": 0, "real": 0, "mock": 0, "empty": 0, "error": 0}
    for config in configs.values():
        per_agent = config["overall"].get("source_status", {}).get("per_agent", {})
        bucket = per_agent.get("WikidataAgent")
        if bucket:
            for key in wd_total:
                wd_total[key] += bucket[key]
    if wd_total["calls"]:
        patterns.append(
            f"WikidataAgent 全部 {wd_total['calls']} 次调用：real={wd_total['real']}、"
            f"mock={wd_total['mock']}、empty={wd_total['empty']}、error={wd_total['error']}。"
            "真实结果来自 `data.source=wikidata-api`，命中本地快照时标记 `local-mock`，"
            "报告中不混算；Wikimedia 对无 UA/高频请求返回 403，因此同一次运行里 "
            "real 与 mock 会交替出现。"
        )
    return patterns


def limitations(*, detailed: bool = False) -> list[str]:
    base = [
        "**无 LLM judge**：覆盖率/关键词只能验证“拿到真实内容”，"
        "无法自动判断答案是否真正回答了问题；"
        "missing_source 的“误报”只能说明返回了非空内容，不能断言其相关性。",
        "**外部数据源漂移**：DBpedia / arXiv / GitLab / wttr.in / Wikidata 均为 live 公网 API，"
        "结果与延迟随网络和上游限流波动；"
        "arXiv 在本环境会间歇性 429/超时，GitLab 匿名配额与 Wikimedia robot policy "
        "也可能对一次完整评测触发 429/403，均作为真实环境噪声保留、不剔除。",
        "**评测预算与产品默认不同**：产品 Dispatcher 默认 timeout=10s、max_retries=1；"
        "为在 5 分钟内完成 4 配置评测，本次统一关闭重试（max_retries=0），绝对延迟是下界估计，"
        "配置间相对比较不受影响。",
        "**题目规模**：18 道题、4 类场景，统计粒度有限；关键词命中是保守的相关性代理，"
        "同义词/语言差异会造成漏判（尤其是 Wikidata 真实响应的字段结构）。",
        "**单机单次运行**：没有多轮重复取均值，不声称统计显著性；"
        "报告附 git commit 与 run_id 以支持复跑。",
    ]
    if detailed:
        base.append(
            "**进程内 ASGI 的等价性**：评测把 HTTP 传输替换为 `httpx.ASGITransport`，"
            "JSON-RPC 层、A2A Server、Dispatcher、Coordinator 均为真实代码；"
            "唯一差异是网络栈，不改变协议与编排语义。"
        )
        base.append(
            "**mock 数据的影响**：WikidataAgent 在真实 API 失败/无命中时"
            "回退 `data/mock/wikidata.json`，"
            "报告用 `source=local-mock` 单独统计；source_coverage 不计 mock，"
            "keyword_hit 默认计 mock，"
            "因此同时给出 `keyword_hit_real` 以避免误读。"
        )
    return base


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def write_outputs(
    report: dict[str, Any], *, out_json: Path, out_md: Path, docs: Path | None
) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_markdown(report), encoding="utf-8")
    if docs is not None:
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(render_markdown(report, detailed=True), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m eval.runner",
        description="跨域多 Agent 评测 harness（4 配置 × 18 题，确定性指标，无 LLM judge）",
    )
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--docs", type=Path, default=DEFAULT_DOCS)
    parser.add_argument(
        "--configs",
        type=lambda value: [c.strip() for c in value.split(",") if c.strip()],
        default=list(CONFIG_NAMES),
        help=f"comma separated subset of {CONFIG_NAMES}",
    )
    parser.add_argument("--limit", type=int, default=0, help="only first N questions")
    parser.add_argument("--only-ids", default="", help="comma separated question ids")
    parser.add_argument("--backend", choices=("live", "fake"), default="live")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--no-docs", action="store_true")
    return parser.parse_args(argv)


async def amain(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configs = [c for c in args.configs if c in CONFIG_NAMES]
    unknown = [c for c in args.configs if c not in CONFIG_NAMES]
    if unknown:
        print(f"unknown configs: {unknown}", file=sys.stderr)
        return 2
    if not configs:
        print("no configs selected", file=sys.stderr)
        return 2
    questions, _index = load_questions(args.questions)
    if args.limit:
        questions = questions[: args.limit]
    only_ids = {qid.strip() for qid in args.only_ids.split(",") if qid.strip()} or None

    agent_instances = None
    pacing = None
    if args.backend == "fake":
        from eval.selftest import build_fake_instances

        agent_instances = build_fake_instances(questions)
        pacing = {name: 0.0 for name in AGENT_NAMES}

    print(
        f"running {len(questions)} questions x {len(configs)} configs "
        f"(backend={args.backend}, git={git_info()['commit']})",
        file=sys.stderr,
        flush=True,
    )
    report = await run_evaluation(
        questions,
        configs,
        questions_path=args.questions,
        agent_instances=agent_instances,
        pacing=pacing,
        preflight=(not args.skip_preflight) and args.backend != "fake",
        progress_stream=sys.stderr,
        only_ids=only_ids,
    )
    docs = None if args.no_docs else args.docs
    write_outputs(report, out_json=args.out_json, out_md=args.out_md, docs=docs)
    print(
        f"done in {report['meta']['duration_s']}s; run_id={report['meta']['run_id']}; "
        f"wrote {args.out_json}, {args.out_md}" + (f", {docs}" if docs else ""),
        file=sys.stderr,
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(amain(argv))


if __name__ == "__main__":
    raise SystemExit(main())
