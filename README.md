# Decentralized Encyclopedia

[![Powered by OrcaRouter](https://img.shields.io/badge/Powered_by-OrcaRouter-2563eb)](https://www.orcarouter.ai/ref/ref_91abafd1d58e1cd93c7f)

多 Agent 协作系统 — 每个 Agent 负责一个知识领域，通过简化版 A2A 协议自主通信，协同回答跨领域复杂问题。

## Architecture

```
                         ┌─────────────────┐
                         │    Web UI        │
                         │  (HTML/JS/CSS)   │
                         └────────┬────────┘
                                  │ REST
                         ┌────────▼────────┐
                         │  Web Server      │
                         │  :8000 (FastAPI) │
                         └────────┬────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │     Coordinator Agent      │
                    │  问题分解 → 路由 → 聚合     │
                    │  (LLM or rule-based)       │
                    └──┬──┬──┬──┬──┬────────────┘
                       │  │  │  │  │
          ┌────────────┘  │  │  │  └────────────┐
          ▼               ▼  ▼  ▼               ▼
     ┌─────────┐  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
     │ DBpedia │  │  arXiv  │ │ GitLab  │ │ wttr.in │ │Wikidata │
     │ :8001   │  │  :8002  │ │  :8003  │ │  :8004  │ │ :8005   │
     └─────────┘  └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

## Simplified A2A Protocol

基于 Google A2A 协议的简化实现，核心概念：

### Agent Card

每个 Agent 在 `/.well-known/agent.json` 暴露能力描述：

```json
{
  "name": "WikipediaAgent",
  "description": "搜索和检索 Wikipedia 百科条目",
  "version": "1.0.0",
  "skills": [{
    "name": "search_articles",
    "description": "按关键词搜索百科文章",
    "input_schema": { "query": "string", "lang": "string" }
  }],
  "transport": "jsonrpc",
  "endpoint": "http://localhost:8001"
}
```

### Message & Part

```python
class Part(BaseModel):
    type: Literal["text", "file", "data"]
    text: str | None = None
    data: Any | None = None
    file_uri: str | None = None

class Message(BaseModel):
    role: Literal["user", "agent"]
    parts: list[Part]
    metadata: dict[str, Any] = {}
```

### Task Lifecycle

```
submitted → working → completed | failed | input-required | canceled
```

### JSON-RPC Transport

```json
// Request
{"jsonrpc": "2.0", "method": "message/send", "params": {"task_id": "abc", "message": {...}}, "id": 1}

// Response
{"jsonrpc": "2.0", "result": {"task_id": "abc", "status": "completed", "message": {...}}, "id": 1}
```

## Project Structure

```
decentralized-encyclopedia/
├── src/
│   ├── protocol/              # Simplified A2A protocol
│   │   ├── models.py          # Pydantic data models (Part, Message, Task, AgentCard)
│   │   ├── server.py          # A2A Server base class (FastAPI)
│   │   ├── client.py          # A2A Client (HTTP JSON-RPC)
│   │   ├── streaming.py       # SSE streaming support
│   │   └── security.py        # API Key authentication
│   ├── agents/                # Domain agents
│   │   ├── base.py            # BaseAgent abstract class
│   │   ├── coordinator.py     # Coordinator: decomposition + routing + aggregation
│   │   ├── wikipedia.py       # DBpedia Agent (real API)
│   │   ├── arxiv.py           # arXiv Agent (real API + query translation)
│   │   ├── github.py          # GitLab Agent (real API + query translation)
│   │   ├── weather.py         # Weather Agent (wttr.in API)
│   │   └── wikidata.py        # Wikidata Agent (Entity Search API + mock fallback)
│   ├── orchestrator/
│   │   ├── registry.py        # Agent registry (dynamic registration + enable/disable)
│   │   ├── router.py          # Hybrid routing (rules + LLM)
│   │   └── dispatcher.py      # Parallel task dispatching
│   ├── llm/
│   │   ├── base.py            # LLM abstraction
│   │   ├── openai_provider.py # OpenAI implementation
│   │   ├── anthropic_provider.py # Anthropic implementation
│   │   ├── orcarouter_provider.py # OrcaRouter (OpenAI-compatible, auto-fallback)
│   │   ├── factory.py         # Provider factory
│   │   └── prompts.py         # Prompt templates
│   ├── utils/
│   │   └── query_translate.py # Chinese→English query translation (dict + LLM)
│   └── web/
│       ├── app.py             # FastAPI web application
│       ├── api.py             # REST API routes
│       └── static/            # Frontend (HTML/JS/CSS)
├── tests/                     # Test suite (121 tests)
├── scripts/
│   ├── start.py               # Start full system (agents + coordinator + web)
│   ├── run_all.py             # Start domain agents only
│   └── stop_all.py            # Stop all processes
├── data/mock/                 # Mock data for fallback
└── pyproject.toml
```

## Quick Start

### 1. Install dependencies

```bash
cd decentralized-encyclopedia
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env to set LLM provider and API keys
```

### 3. Start the system

```bash
uv run python scripts/start.py
```

This starts:
- 5 domain agents on ports 8001-8005
- Coordinator (with optional LLM)
- Web server on port 8000

### 4. Open Web UI

Visit `http://localhost:8000` and ask a cross-domain question.

### Example queries

- "量子计算的最新研究进展有哪些？有哪些开源实现？"
- "北京的气候特征是什么？相关的学术研究有哪些？"
- "爱因斯坦在哪所大学任教？他的学生有哪些？"

## LLM Providers

The system works without LLM (rule-based fallback). Configure an LLM provider for smarter query decomposition and result aggregation.

| Provider | Env Config | Default Model |
|----------|-----------|---------------|
| OrcaRouter | `LLM_PROVIDER=orca` + `ORCAROUTER_API_KEY` | orcarouter/free |
| OpenAI | `LLM_PROVIDER=openai` + `OPENAI_API_KEY` | gpt-4o |
| Anthropic | `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` | claude-sonnet-4 |

### OrcaRouter (Recommended)

[OrcaRouter](https://www.orcarouter.ai) is an OpenAI-compatible API gateway with free models and automatic model fallback.

```bash
# .env
LLM_PROVIDER=orca
ORCAROUTER_API_KEY=sk-orca-your-key
ORCAROUTER_MODEL=orcarouter/free  # optional, uses default if not set
```

Fallback chain: `orcarouter/free` → `deepseek/deepseek-v4-flash-free` → `tencent/hy3-free` → `qwen/qwen3.8-27b-free`

## Chinese Query Support

All agents support Chinese queries natively or via automatic translation:

- **DBpedia / wttr.in / Wikidata**: API supports Chinese directly
- **arXiv / GitLab**: `QueryTranslator` converts Chinese keywords to English (dictionary + optional LLM)

## Running Tests

```bash
uv run pytest tests/ -v
```

## Tech Stack

- **Python 3.11+** / **uv** (package manager)
- **FastAPI** / **uvicorn** (HTTP server)
- **Pydantic** (data validation)
- **httpx** (async HTTP client)
- **sse-starlette** (Server-Sent Events)
- **OrcaRouter** / **OpenAI** / **Anthropic** (optional LLM providers)

## License

MIT
