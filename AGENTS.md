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
- **Agents** (`src/agents/`): `BaseAgent` abstract class → `handle_message()`. `Coordinator` does decomposition → routing → aggregation. Domain agents each expose one FastAPI app via `A2AServer`.
- **Orchestrator** (`src/orchestrator/`): `AgentRegistry` (dynamic registration, enable/disable), `Router` (keyword rules + optional LLM fallback), `Dispatcher` (parallel dispatch with retries).
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

Copy `.env.example` to `.env` to configure LLM provider. System works without LLM (rule-based fallback). All external APIs are free and require no API key. Optional `A2A_API_KEY` for inter-agent auth.

## LLM Providers

| Provider | Env Config | Default Model | Notes |
|----------|-----------|---------------|-------|
| OpenAI | `LLM_PROVIDER=openai` + `OPENAI_API_KEY` | gpt-4o | Standard OpenAI |
| Anthropic | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` | claude-sonnet-4 | Anthropic SDK |
| OrcaRouter | `LLM_PROVIDER=orca` + `ORCAROUTER_API_KEY` | orcarouter/free | OpenAI 兼容网关，支持模型自动降级 |

OrcaRouter 特性：
- API key 以 `sk-orca-` 开头
- 模型由 `ORCAROUTER_MODEL` 环境变量配置，未配置用默认模型 `orcarouter/free`
- 调用失败时自动降级到 fallback 模型：`deepseek/deepseek-v4-flash-free` → `tencent/hy3-free` → `qwen/qwen3.8-27b-free`
- 提供免费模型（DeepSeek、腾讯混元、千问等）

## External API Dependencies

| Agent | API | Free/No Key | 中文查询 |
|-------|-----|-------------|---------|
| WikipediaAgent | DBpedia Lookup API | ✅ | ✅ 支持 |
| ArxivAgent | arXiv API | ✅ | ✅ 中文关键词自动翻译为英文（`QueryTranslator`） |
| GithubAgent | GitLab API | ✅ | ✅ 中文关键词自动翻译为英文（`QueryTranslator`） |
| WeatherAgent | wttr.in | ✅ | ✅ 支持 |
| WikidataAgent | Wikidata Entity Search API (+ mock fallback) | ✅ | ✅ API 用 `language=zh` 搜索中文实体 |

## Chinese Query Translation

`src/utils/query_translate.py` provides `QueryTranslator` for Chinese→English translation:

- **Dictionary mode** (default): matches ~40 high-frequency Chinese technical terms
- **LLM mode** (when LLM configured): uses LLM for natural translation, falls back to dictionary on failure

ArxivAgent and GithubAgent use `QueryTranslator` automatically. WikidataAgent uses `language=zh` directly.
