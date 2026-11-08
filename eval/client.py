"""In-process ASGI runtime for the cross-domain evaluation harness.

The whole point of this module is to drive the *real* product code path without
opening any TCP ports: each domain agent is instantiated with its canonical
:class:`~src.protocol.models.AgentCard` (from ``src.agents.catalog``), its
FastAPI app is served through ``httpx.ASGITransport``, and the real
:class:`~src.protocol.client.A2AClient` / :class:`~src.orchestrator.dispatcher.Dispatcher`
/ :class:`~src.agents.coordinator.Coordinator` objects are used unchanged.

Only transport is redirected (HTTP -> ASGI), which keeps the evaluation
faithful to the shipped system while remaining hermetic and fast.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.agents.catalog import AGENT_SPECS, build_card
from src.agents.coordinator import Coordinator
from src.orchestrator.dispatcher import Dispatcher, DispatchResult
from src.orchestrator.registry import AgentRegistry
from src.orchestrator.router import Router
from src.protocol.client import A2AClient
from src.protocol.models import Message, Part, Task, TaskState

AGENT_NAMES: tuple[str, ...] = tuple(spec.name for spec in AGENT_SPECS)

# Per-source minimum interval between request *starts* (seconds). These are
# deliberately conservative: arXiv's robots policy asks for >= 3 s between
# requests, Wikimedia asks clients to be serial and identify themselves, and
# the free DBpedia/GitLab/wttr.in endpoints are shared infrastructure. The
# pace only delays the start of a request; it does not serialise sources.
DEFAULT_PACING: dict[str, float] = {
    "WikipediaAgent": 1.0,
    "ArxivAgent": 3.0,
    # GitLab.com applies an unauthenticated traffic quota per IP; a fast
    # 4-config sweep can trip it (HTTP 429 for every later search call).
    "GithubAgent": 2.0,
    "WeatherAgent": 1.0,
    # Wikimedia asks clients to be serial; bursts trigger the robot-policy 403.
    "WikidataAgent": 1.5,
}

# Evaluation budget (identical for all four configs; only routing/scheduling
# changes between them). The product dispatcher defaults are timeout=10s,
# max_retries=1; the retry is disabled here because arXiv is known to be
# rate-limited in this environment (35 arxiv calls x (10s timeout + 1s backoff
# + 10s retry) alone would exceed the 5-minute run budget). Absolute latency
# numbers are therefore lower-bound estimates; relative comparisons are
# unaffected. This is documented in docs/eval-report.md.
DEFAULT_AGENT_TIMEOUT = 10.0
DEFAULT_MAX_RETRIES = 0

# Per-source timeout overrides. arXiv is the only upstream that is chronically
# slow/throttled from this host (see docs/eval-report.md); a shorter budget for
# ArxivAgent keeps a full 4-config run under the 5-minute budget while still
# recording every timeout as a real error instead of hiding it.
DEFAULT_TIMEOUTS: dict[str, float] = {
    "WikipediaAgent": 10.0,
    "ArxivAgent": 6.0,
    "GithubAgent": 10.0,
    "WeatherAgent": 10.0,
    "WikidataAgent": 10.0,
}


class AgentCallTimeout(Exception):
    """Raised when a single agent call exceeds its per-source eval budget."""

CONFIG_NAMES: tuple[str, ...] = ("single", "multi_serial", "multi_parallel", "all_agents")


# --------------------------------------------------------------------------- #
# small utilities
# --------------------------------------------------------------------------- #
class Pacer:
    """Enforce a minimum gap between two calls to the same upstream source."""

    def __init__(self, intervals: dict[str, float]):
        self._intervals = dict(intervals)
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_start: dict[str, float] = {}

    async def wait(self, agent: str) -> None:
        interval = self._intervals.get(agent, 0.0)
        lock = self._locks.setdefault(agent, asyncio.Lock())
        async with lock:
            if interval > 0:
                last = self._last_start.get(agent)
                if last is not None:
                    gap = interval - (time.monotonic() - last)
                    if gap > 0:
                        await asyncio.sleep(gap)
            self._last_start[agent] = time.monotonic()


@dataclass
class AgentCall:
    """One logical agent invocation (all retries folded into ``attempts``)."""

    agent: str
    query: str
    status: str  # real | mock | empty | error
    latency_ms: float
    attempts: int = 1
    result_count: int = 0
    has_real_result: bool = False
    data_source: str | None = None
    terminal_state: str | None = None
    error: str | None = None
    text: str = ""
    data_preview: str = ""
    keyword: str | None = None
    keyword_hit: bool | None = None
    keyword_hit_real: bool | None = None
    # not serialised: keeps the raw Task for aggregation in the runner
    task: Any = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        out = {
            "agent": self.agent,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 2),
            "attempts": self.attempts,
            "result_count": self.result_count,
            "has_real_result": self.has_real_result,
            "data_source": self.data_source,
            "terminal_state": self.terminal_state,
            "keyword": self.keyword,
            "keyword_hit": self.keyword_hit,
            "keyword_hit_real": self.keyword_hit_real,
            "text": self.text,
            "data_preview": self.data_preview,
        }
        if self.error:
            out["error"] = self.error
        if self.query and self.query not in (None, ""):
            out["query"] = self.query
        return out


@dataclass
class ConfigRun:
    """Result of running one question under one configuration."""

    question_id: str
    config: str
    question: str
    routed_agents: list[str]
    called_agents: list[str]
    calls: list[AgentCall]
    elapsed_ms: float
    answer: str = ""
    process_log: list[str] = field(default_factory=list)
    error: str | None = None
    routing_consistent: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "config": self.config,
            "question": self.question,
            "routed_agents": self.routed_agents,
            "called_agents": self.called_agents,
            "calls": [c.to_dict() for c in self.calls],
            "elapsed_ms": round(self.elapsed_ms, 2),
            "answer": self.answer,
            "process_log": self.process_log,
            "error": self.error,
            "routing_consistent": self.routing_consistent,
        }


# --------------------------------------------------------------------------- #
# ASGI-backed A2A client (transport redirection only)
# --------------------------------------------------------------------------- #
class ASGIA2AClient(A2AClient):
    """``A2AClient`` whose HTTP client is bound to a FastAPI app via ASGI.

    Behaves exactly like the production client; the injected ``http_client``
    has ``base_url == card.url`` so the absolute JSON-RPC URL resolves into the
    in-process transport.
    """

    def __init__(self, base_url: str, runtime: AgentRuntime, api_key: str | None = None):
        self._runtime = runtime
        self.agent = runtime.agent_for_url(base_url)
        http = runtime.make_http_client(base_url, self.agent)
        super().__init__(base_url=base_url, api_key=api_key, http_client=http)

    async def send_message(
        self, message: Message, task_id: str | None = None, context_id: str | None = None
    ) -> Task:
        await self._runtime.pacer.wait(self.agent)
        timeout = self._runtime.timeout_for(self.agent)
        started = time.perf_counter()
        try:
            return await asyncio.wait_for(
                super().send_message(message, task_id=task_id, context_id=context_id),
                timeout=timeout,
            )
        except TimeoutError:
            raise AgentCallTimeout(f"timeout after {timeout:.1f}s") from None
        finally:
            self._runtime.record_attempt(self.agent, (time.perf_counter() - started) * 1000.0)


class RecordingDispatcher(Dispatcher):
    """Real dispatcher that keeps the per-agent outcomes for metrics."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.last_results: list[DispatchResult] = []

    async def dispatch(self, tasks, send_fn, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        results = await super().dispatch(tasks, send_fn, *args, **kwargs)
        self.last_results = list(results)
        return results


# --------------------------------------------------------------------------- #
# response classification
# --------------------------------------------------------------------------- #
_WIKIDATA_MOCK_SOURCE = "local-mock"


def _walk_source(value: Any) -> str | None:
    """Find a ``source`` marker anywhere in a returned data payload."""
    if isinstance(value, dict):
        source = value.get("source")
        if isinstance(source, str):
            return source
        for v in value.values():
            found = _walk_source(v)
            if found is not None:
                return found
    elif isinstance(value, list):
        for v in value:
            found = _walk_source(v)
            if found is not None:
                return found
    return None


def _result_count(data: Any) -> int:
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return len(results)
        return 1 if data else 0
    if isinstance(data, list):
        return len(data)
    return 0 if data is None else 1


def _content_of(text: str, data: Any) -> str:
    try:
        rendered = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        rendered = str(data)
    return f"{text}\n{rendered}"


def classify_task(
    task: Task | None,
    agent: str,
    query: str,
    keyword: str | None,
    *,
    error: str | None = None,
    latency_ms: float = 0.0,
    attempts: int = 1,
) -> AgentCall:
    """Turn the A2A ``Task`` (or a transport error) into a flat metric record."""
    if task is None:
        return AgentCall(
            agent=agent,
            query=query,
            status="error",
            latency_ms=latency_ms,
            attempts=attempts,
            error=error or "no task returned",
            keyword=keyword,
            keyword_hit=False if keyword else None,
            keyword_hit_real=False if keyword else None,
        )

    state = getattr(getattr(task, "status", None), "state", None)
    history = getattr(task, "history", None) or []
    agent_messages = [m for m in history if getattr(m, "role", None) == "agent"]
    texts: list[str] = []
    data_parts: list[Any] = []
    for message in agent_messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "kind", None) == "text" and part.text:
                texts.append(part.text)
            elif getattr(part, "kind", None) == "data" and part.data is not None:
                data_parts.append(part.data)
    text = "\n".join(texts)
    data = data_parts[-1] if data_parts else None
    source = _walk_source(data)

    failure: str | None = None
    if state == TaskState.FAILED or getattr(state, "value", None) == "failed":
        status_message = getattr(getattr(task, "status", None), "message", None)
        metadata = getattr(status_message, "metadata", None) or {}
        failure = metadata.get("error") or text or "task failed"
    elif text.startswith("Error:"):
        failure = text
    elif "Failed to get weather" in text:
        failure = text

    if failure is not None:
        status = "error"
    elif source == _WIKIDATA_MOCK_SOURCE:
        status = "mock"
    elif data is not None:
        status = "real"
    else:
        status = "empty"

    result_count = _result_count(data) if status != "error" else 0
    has_real_result = status == "real" and result_count > 0
    content = _content_of(text, data) if data is not None else text
    keyword_hit = (keyword.lower() in content.lower()) if keyword else None
    keyword_hit_real = bool(keyword_hit and status == "real") if keyword else None
    term_state = getattr(state, "value", state)
    try:
        data_preview = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        data_preview = str(data)
    if len(data_preview) > 700:
        data_preview = data_preview[:700] + "…"
    if len(text) > 700:
        text = text[:700] + "…"

    return AgentCall(
        agent=agent,
        query=query,
        status=status,
        latency_ms=latency_ms,
        attempts=attempts,
        result_count=result_count,
        has_real_result=has_real_result,
        data_source=source,
        terminal_state=str(term_state),
        error=failure,
        text=text,
        data_preview=data_preview,
        keyword=keyword,
        keyword_hit=keyword_hit,
        keyword_hit_real=keyword_hit_real,
        task=task,
    )


# --------------------------------------------------------------------------- #
# runtime
# --------------------------------------------------------------------------- #
class AgentRuntime:
    """Builds the five agents + orchestrator in-process and runs the 4 configs."""

    def __init__(
        self,
        agent_instances: dict[str, Any] | None = None,
        pacing: dict[str, float] | None = None,
        agent_timeout: float = DEFAULT_AGENT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeouts: dict[str, float] | None = None,
    ):
        self.cards: dict[str, Any] = {}
        self.apps: dict[str, Any] = {}
        self.instances: dict[str, Any] = {}
        self._url_to_agent: dict[str, str] = {}
        for spec in AGENT_SPECS:
            card = build_card(spec)
            self.cards[spec.name] = card
            self._url_to_agent[card.url.rstrip("/")] = spec.name
            if agent_instances is not None:
                instance = agent_instances[spec.name]
            else:
                module = importlib.import_module(spec.module)
                instance = getattr(module, spec.class_name)(card=card)
            self.instances[spec.name] = instance
            _wire_handle_message(instance)
            self.apps[spec.name] = _app_of(instance)

        self.pacer = Pacer(pacing or DEFAULT_PACING)
        self.agent_timeout = agent_timeout
        self.timeouts = {**DEFAULT_TIMEOUTS, **(timeouts or {})}
        self.max_retries = max_retries
        self._attempts: dict[str, list[float]] = {}

        # Canonical routing.
        self.registry = AgentRegistry()
        for name in AGENT_NAMES:
            self.registry.register_sync(self.cards[name])
        self.router = Router(registry=self.registry)

        # Real product coordinator with a recording dispatcher, so
        # multi_parallel exercises decompose -> parallel dispatch -> aggregate.
        self.dispatcher = RecordingDispatcher(timeout=agent_timeout, max_retries=max_retries)
        self.coordinator = Coordinator(
            registry=self.registry,
            router=self.router,
            dispatcher=self.dispatcher,
            llm=None,
        )
        self._patch_dispatcher_client()

    # ------------------------------------------------------------- plumbing
    def _patch_dispatcher_client(self) -> None:
        """Make the real Dispatcher use the ASGI-backed client factory."""
        import src.orchestrator.dispatcher as dispatcher_module

        runtime = self

        def factory(base_url: str, api_key: str | None = None, http_client: Any = None):
            return ASGIA2AClient(base_url=base_url, runtime=runtime, api_key=api_key)

        self._real_dispatcher_client = dispatcher_module.A2AClient
        dispatcher_module.A2AClient = factory  # type: ignore[assignment]

    def close(self) -> None:
        """Restore the production client class (idempotent)."""
        module = importlib.import_module("src.orchestrator.dispatcher")
        if getattr(self, "_real_dispatcher_client", None) is not None:
            module.A2AClient = self._real_dispatcher_client  # type: ignore[assignment]
            self._real_dispatcher_client = None

    def timeout_for(self, agent: str) -> float:
        return self.timeouts.get(agent, self.agent_timeout)

    def agent_for_url(self, base_url: str) -> str:
        key = base_url.rstrip("/")
        if key not in self._url_to_agent:
            raise KeyError(f"unknown agent url: {base_url}")
        return self._url_to_agent[key]

    def make_http_client(self, base_url: str, agent: str) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=self.apps[agent])
        return httpx.AsyncClient(
            transport=transport,
            base_url=base_url,
            timeout=httpx.Timeout(self.agent_timeout + 15.0),
        )

    def record_attempt(self, agent: str, latency_ms: float) -> None:
        self._attempts.setdefault(agent, []).append(latency_ms)

    def _take_attempts(self, agent: str) -> list[float]:
        return self._attempts.pop(agent, [])

    # ------------------------------------------------------------- routing
    def route_cards(self, query: str) -> list[Any]:
        """Same routing as ``Coordinator._rule_decompose`` (incl. fallback)."""
        cards = self.router.rule_match(query)
        if not cards:
            cards = self.registry.get_enabled()[:3]
        return cards

    # ------------------------------------------------------------- invocation
    async def _send_once(
        self, agent: str, query: str
    ) -> tuple[Task | None, float, int, str | None]:
        """One agent call with the same timeout/retry budget as the dispatcher."""
        card = self.cards[agent]
        last_error: str | None = None
        total_latency = 0.0
        attempts = 0
        for attempt in range(self.max_retries + 1):
            attempts += 1
            client = ASGIA2AClient(base_url=card.url, runtime=self)
            try:
                message = Message(role="user", parts=[Part(kind="text", text=query)])
                task = await asyncio.wait_for(
                    client.send_message(message), timeout=self.timeout_for(agent) + 1.0
                )
                elapsed = self._take_attempts(agent)
                return task, total_latency + (sum(elapsed) if elapsed else 0.0), attempts, None
            except TimeoutError:
                last_error = f"TimeoutError: agent call exceeded {self.timeout_for(agent):.1f}s"
            except Exception as exc:  # noqa: BLE001 - recorded as source status
                last_error = f"{type(exc).__name__}: {exc}"
            finally:
                await client.http.aclose()
            total_latency += sum(self._take_attempts(agent))
            if attempt < self.max_retries:
                await asyncio.sleep(1.0)
        return None, total_latency, attempts, last_error

    async def invoke(self, agent: str, query: str, keyword: str | None = None) -> AgentCall:
        task, latency, attempts, error = await self._send_once(agent, query)
        return classify_task(
            task, agent, query, keyword,
            error=error, latency_ms=latency, attempts=attempts,
        )

    async def invoke_many(
        self, agents: Iterable[str], query: str, keywords: dict[str, str] | None = None
    ) -> list[AgentCall]:
        keywords = keywords or {}
        return [await self.invoke(agent, query, keywords.get(agent)) for agent in agents]

    # ------------------------------------------------------------- configs
    def _results_from_calls(self, calls: list[AgentCall]) -> list[DispatchResult]:
        results: list[DispatchResult] = []
        for call in calls:
            card = self.cards[call.agent]
            if call.task is not None:
                results.append(DispatchResult(card=card, task=call.task))
            else:
                results.append(DispatchResult(card=card, error=call.error or "unknown error"))
        return results

    async def run_config(self, config: str, question: dict[str, Any]) -> ConfigRun:
        qid = question["id"]
        query = question["question"]
        expected_keywords: dict[str, str] = question.get("expected_keywords") or {}
        routed_cards = self.route_cards(query)
        routed_names = [c.name for c in routed_cards]

        started = time.perf_counter()
        process_log: list[str] = []
        error: str | None = None
        routing_consistent: bool | None = None
        calls: list[AgentCall] = []

        try:
            if config == "multi_parallel":
                task = Task(id=f"eval-{qid}")
                message = Message(role="user", parts=[Part(kind="text", text=query)])
                answer_msg = await self.coordinator.handle_message(message, task)
                results = list(self.dispatcher.last_results)
                calls = [
                    self._call_from_dispatch(result, query, expected_keywords)
                    for result in results
                ]
                called_names = [c.agent for c in calls]
                routing_consistent = sorted(called_names) == sorted(routed_names)
                process_log = list(self.coordinator._process_log)
                answer = answer_msg.parts[0].text if answer_msg.parts else ""
            else:
                if config == "single":
                    targets = routed_names[:1]
                elif config == "multi_serial":
                    targets = list(routed_names)
                elif config == "all_agents":
                    targets = list(AGENT_NAMES)
                else:
                    raise ValueError(f"unknown config: {config}")
                if config in ("all_agents",):
                    calls = list(
                        await asyncio.gather(
                            *(
                                self.invoke(name, query, expected_keywords.get(name))
                                for name in targets
                            )
                        )
                    )
                else:
                    calls = []
                    for name in targets:
                        calls.append(await self.invoke(name, query, expected_keywords.get(name)))
                results = self._results_from_calls(calls)
                answer = await self.coordinator.aggregate(query, results)
                called_names = [c.agent for c in calls]
        except Exception as exc:  # noqa: BLE001 - config-level failure is data
            error = f"{type(exc).__name__}: {exc}"
            called_names = [c.agent for c in calls]
            answer = ""

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return ConfigRun(
            question_id=qid,
            config=config,
            question=query,
            routed_agents=routed_names,
            called_agents=called_names,
            calls=calls,
            elapsed_ms=elapsed_ms,
            answer=answer,
            process_log=process_log,
            error=error,
            routing_consistent=routing_consistent,
        )

    def _call_from_dispatch(
        self, result: DispatchResult, query: str, expected_keywords: dict[str, str]
    ) -> AgentCall:
        agent = result.card.name
        attempts = self._take_attempts(agent)
        latency = sum(attempts)
        keyword = expected_keywords.get(agent)
        if result.task is None:
            return classify_task(
                None, agent, query, keyword,
                error=result.error or "dispatch failed",
                latency_ms=latency,
                attempts=max(1, len(attempts)),
            )
        return classify_task(
            result.task, agent, query, keyword,
            latency_ms=latency,
            attempts=max(1, len(attempts)),
        )


def _wire_handle_message(instance: Any) -> None:
    """Replicate ``BaseAgent.start()`` wiring without binding a TCP port.

    ``BaseAgent.start`` does ``self.server.handle_message = self.handle_message``
    before handing the app to uvicorn; in-process evaluation must do the same or
    the server would keep raising ``NotImplementedError``.
    """
    server = getattr(instance, "server", None)
    handler = getattr(instance, "handle_message", None)
    if server is not None and handler is not None and hasattr(server, "handle_message"):
        server.handle_message = handler


def _app_of(instance: Any) -> Any:
    """Return the FastAPI app of a live agent or an A2AServer instance."""
    if hasattr(instance, "server") and hasattr(instance.server, "app"):
        return instance.server.app
    if hasattr(instance, "app"):
        return instance.app
    raise TypeError(f"cannot locate ASGI app on {instance!r}")
