# AGENTS.md

本文件给"接手这个仓库的人/编码 Agent"看：怎么跑、结构在哪、什么不能动。

## Commands

```bash
uv sync                      # 安装依赖（默认无 LLM 即可运行）
uv run pytest tests/ -q      # 全部测试（150 个，全离线，约 4s）
uv run python scripts/start.py   # 启动完整系统（5 agents + Coordinator + Web）
uv run python scripts/run_all.py # 只启动 5 个 domain agents（无 Coordinator/Web）
uv run python scripts/stop_all.py # 清理 8000–8005 端口上的残留进程
make eval                    # 跨域评测（4 种路由/调度配置，见 eval/README.md）
```

静态检查（CI 同款）：

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/ -q --cov=src --cov-fail-under=80
```

## Startup gotcha

`scripts/start.py` 会拉起完整链路；`scripts/run_all.py` **只启动 domain agents**，
不启动 Coordinator 与 Web Server，也没有 `/api/query`。Coordinator 是 **Web 进程内的对象**，
**没有独立端口**（早期版本曾打印 "Coordinator: port 8010"，那是错的）。

## Port map

| Service | Port | Note |
|---|---|---|
| Web UI / API | 8000 | `/api/query`、`/api/agents` |
| WikipediaAgent | 8001 | DBpedia Lookup |
| ArxivAgent | 8002 | arXiv API |
| GithubAgent | 8003 | GitLab API（不是 GitHub） |
| WeatherAgent | 8004 | wttr.in |
| WikidataAgent | 8005 | Wikidata API + 本地 mock 兜底 |
| Coordinator | — | 进程内对象，无端口 |

## Architecture

```
Web UI (static) → FastAPI /api/query → Coordinator
                                        ├─ Router（有序关键词规则 + 可选 LLM 路由）
                                        ├─ Dispatcher（并行 + 超时 + 重试）
                                        └─ A2AClient ──JSON-RPC──▶ 5 个 domain agents（各自独立进程/端口）
```

- **协议层** `src/protocol/`：A2A v0.3 风格 JSON-RPC 子集（Agent Card / `message/send` /
  `tasks/get` / `tasks/cancel` / Task 状态机 / 错误码）。**范围与偏差见 `docs/protocol.md`**。
- **编排层** `src/orchestrator/`：`Registry`（Agent Card 注册/启停）、`Router`（确定性规则，
  顺序即优先级）、`Dispatcher`（信号量限流并行 + 指数退避重试，失败保留在 `DispatchResult`）。
- **Agent 层** `src/agents/`：`BaseAgent` + 5 个数据源适配；Agent Card 集中在
  `src/agents/catalog.py`（不要在启动脚本里手拼空卡片）。
- **LLM 层** `src/llm/`：可选。未配置时全程规则模式（规则路由 + 规则聚合），
  配置后用于查询分解 / 路由 / 聚合；**LLM 失败必须降级到规则，不能 500**。
- **Web 层** `src/web/`：`/api/query` 返回 `{answer, process}`；前端 `static/app.js`
  只渲染一个很小的 Markdown 子集（标题/列表/引用/粗体/链接）。

## 不可让步的约定

1. **不要声称实现了 A2A 协议**：它是 A2A v0.3 风格子集，未迁移 v1.0、未实现流式。
   对外表述以 `docs/protocol.md` 为准。
2. **架构是中心调度（hub-and-spoke），不是 P2P**：domain agents 之间不互相通信。
3. **数据源失败要显式暴露**：`DispatchResult.error` 与 `source: "local-mock"` 必须传到
   聚合结果和 process log，不许静默吞掉。
4. **不得引入推广/返利性质的依赖或链接**。
5. 外部 API 都是免费公开接口，**不要提交任何密钥**；`.env` 已在 `.gitignore`。

## Testing

- `pytest-asyncio`（`asyncio_mode = "auto"`），测试全部离线：外部 HTTP 一律 mock 或使用
  `httpx.ASGITransport` 进程内调用。
- 契约测试在 `tests/test_integration.py`（客户端 ↔ 服务端、错误码、状态机）与
  `tests/test_agent_cards.py`（Agent Card 必填字段/可发现性）；改动协议必须同步更新这两处。
- 覆盖率门禁 80%（CI）。

## Environment

```bash
cp .env.example .env   # 可选：不配也能跑（规则模式）
```

可选 LLM provider（OpenAI / Anthropic / 任何 OpenAI 兼容网关）见 `.env.example`。
数据源无需任何 key。
