# eval/ — 跨域多 Agent 评测 harness

对 `decentralized-encyclopedia` 的 5 域 Agent + Coordinator 做**确定性、可复现**的对照评测：
一条 `python -m eval.runner` 跑 **18 道中文跨领域问题 × 4 种编排配置**，输出机器可读 JSON 与
Markdown 报告（`reports/eval-latest.{json,md}`、`docs/eval-report.md`）。

- **无 LLM key / 无 LLM judge**：全链路走规则路由 + 规则聚合，指标全部由结构化响应与计时推导。
- **不占用 8000–8005 端口**：5 个 FastAPI agent app 通过 `httpx.ASGITransport` 进程内驱动，
  JSON-RPC 层、A2A Server、Dispatcher、Coordinator 均为真实产品代码。
- **不伪造数据源**：上游不可用/限流→`error`，Wikidata 回退本地快照→`mock`（读 `data.source` 字段），
  报告中如实统计，绝不把 mock 计为真实结果。

## 快速开始

```bash
cd /Users/Admin1/MiMoCode/decentralized-encyclopedia

# 完整评测（live 网络，约 3–5 分钟，18 题 × 4 配置）
.venv/bin/python -m eval.runner

# 冒烟（只跑前 2 题）
.venv/bin/python -m eval.runner --limit 2 --out-json /tmp/eval.json --out-md /tmp/eval.md --no-docs

# 只跑某个配置 / 指定题目
.venv/bin/python -m eval.runner --configs multi_parallel
.venv/bin/python -m eval.runner --only-ids ss-arxiv-01,cs-arxiv-gitlab-01

# 无网络确定性自测（fake ASGI agents，校验 harness 与指标计算）
.venv/bin/python -m eval.selftest

# CI 同款 lint（eval/ 必须保持零告警）
.venv/bin/python -m ruff check eval
```

## 四种配置

| 配置 | 实现（只变路由/调度，聚合层统一用 `Coordinator.aggregate`） |
|---|---|
| `single` | `Router.rule_match(q)[:1]`，单次串行调用，模拟“单 Agent 直答” |
| `multi_serial` | `Router.rule_match(q)` 全部 agent 串行调用 |
| `multi_parallel` | 真实 `Coordinator.handle_message`（规则路由 + 真实 `Dispatcher` 并行/超时/聚合），产品端到端路径 |
| `all_agents` | 固定调用全部 5 个 agent 并行，成本上限对照 |

规则未命中时与 `Coordinator._rule_decompose` 一致，回退 `registry.get_enabled()[:3]`；
每题按题号轮转 4 配置顺序，抵消配置先后与外部缓存造成的顺序效应。

## 指标（全部确定性，可复算）

| 指标 | 定义 |
|---|---|
| `source_coverage` | `expected_agents` 中返回**非空真实结果**的占比（按可答题平均；mock 不算真实） |
| `keyword_hit` | `expected_keywords` 命中返回内容的占比（含 mock 来源） |
| `keyword_hit_real` | 同上，仅统计 `status=real` 的来源 |
| `effective_rate` | 可答题中至少 1 个期望数据源返回非空真实结果的占比 |
| `latency_p50/p95_ms` | 每题端到端耗时（含聚合）的 p50/p95 |
| `agent_calls_avg` | 平均每题 agent 调用次数 |
| `source_status` | 每个数据源 real / mock / empty / error 的调用占比 |
| `routing_precision/recall` | 实际调用集合与 `expected_agents` 的交集占比 |
| `spurious_result_rate_missing_source` | 无对应数据源的题上仍返回非空真实结果的占比（越低越好） |

逐题明细、按 category 分组、失败样本与局限声明均写入 Markdown 报告。

## 题目集（`questions.jsonl`）

每行一个 JSON 对象，字段：

```json
{"id": "cs-arxiv-gitlab-01", "category": "cross_source", "question": "量子计算的论文和开源代码仓库",
 "expected_agents": ["ArxivAgent", "GithubAgent"],
 "expected_keywords": {"ArxivAgent": "quantum", "GithubAgent": "quantum"},
 "notes": "跨‘论文+代码’双源题……"}
```

- `category`：`single_source` / `cross_source` / `missing_source` / `ambiguous`
- `missing_source`：系统没有对应数据源，`expected_agents` 为空、`expected_keywords` 为空；
  该类别不计入 coverage/keyword 平均值，单独用 `spurious_result_rate` 衡量“无源仍作答”。
- 新增题目只需追加一行，`eval.runner` 会自动纳入统计。

## 环境与已知噪声

- 5 个数据源均为 live 公网 API：DBpedia Lookup / arXiv / GitLab / wttr.in / Wikidata；
  上游可用性本身是评测对象的一部分，**失败样本不剔除**。
- Wikidata 需带 User-Agent（否则 Wikimedia robot policy 403）；Agent 已带 UA，
  真实结果 `data.source="wikidata-api"`，本地快照回退 `data.source="local-mock"`。
- arXiv 在本机网络会间歇性 429/超时；评测对 `ArxivAgent` 使用 6s 超时、其余 agent 10s，
  统一 `max_retries=0`（产品默认 1），以保证单次运行 <5 分钟——绝对延迟是下界估计，
  配置间相对比较不受影响。
- 复现实验记录：报告 meta 中有 `git.commit`、`run_id`、上游探针结果、全部 agent 调用明细。

## 目录

```
eval/
├── __init__.py
├── questions.jsonl   # 18 道题（4 类 x 4-5 题）
├── client.py         # 进程内 ASGI runtime + 4 配置执行器 + 响应分类（real/mock/empty/error）
├── metrics.py        # 纯函数指标计算（coverage/keyword/effective/latency/calls/source_status/报告聚合）
├── runner.py         # CLI、评测循环、JSON + Markdown 报告渲染
├── selftest.py       # 无网络 fake backend 自测（与 live 运行共用同一 runtime/Coordinator 路径）
└── README.md
```
