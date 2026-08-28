# AGENTS.md

## Commands

```bash
uv sync                         # install deps
uv run pytest tests/ -v         # run all tests
uv run pytest tests/test_web.py -v  # single test file
uv run python scripts/start.py     # start full system (agents + coordinator + web)
uv run python scripts/stop_all.py  # kill processes on known ports
```

## Startup gotcha

`scripts/start.py` starts the full system: 5 domain agents + Coordinator + Web Server. `scripts/run_all.py` only starts the 5 domain agents and does **not** wire up the Coordinator or Web Server.

## Architecture

- **Protocol layer** (`src/protocol/`): Simplified A2A — JSON-RPC over HTTP. `A2AServer` (FastAPI app per agent), `A2AClient` (httpx async caller), `TaskStore` (in-memory, TTL-evicted). Agent cards served at `/.well-known/agent.json`.
- **Agents** (`src/agents/`): `BaseAgent` abstract class → `handle_message()`. `Coordinator` does decomposition → routing → aggregation. Domain agents (Wikipedia, arXiv, GitHub, Weather, Wikidata) each expose one FastAPI app via `A2AServer`.
- **Orchestrator** (`src/orchestrator/`): `AgentRegistry` (dynamic registration), `Router` (keyword rules + optional LLM fallback), `Dispatcher` (parallel dispatch with retries).
- **LLM** (`src/llm/`): Optional. Factory pattern (`create_llm_provider("openai"|"anthropic")`). When no LLM is configured, the system falls back to rule-based routing and simple text aggregation.
- **Web** (`src/web/`): FastAPI app with REST API (`/api/query`, `/api/agents`) and static frontend in `src/web/static/`.

## Port map

| Service        | Port |
|----------------|------|
| Web UI/Server  | 8000 |
| WikipediaAgent | 8001 |
| ArxivAgent     | 8002 |
| GithubAgent    | 8003 |
| WeatherAgent   | 8004 |
| WikidataAgent  | 8005 |
| Coordinator    | 8010 |

## Import style

All imports use `src.` prefix (src-layout). Example: `from src.protocol.models import Message`.

## Testing

- `pytest-asyncio` with `asyncio_mode = "auto"` — no need to mark individual tests `@pytest.mark.asyncio` (but existing tests still use the decorator).
- Tests use `httpx.AsyncClient` with `ASGITransport` for in-process testing — no real servers needed.
- `tests/test_integration.py` defines a local `EchoAgent` for roundtrip tests.

## Environment

Copy `.env.example` to `.env` to configure LLM provider. System works without LLM (rule-based fallback). WeatherAgent uses wttr.in (no API key needed). Optional `A2A_API_KEY` for inter-agent auth.
