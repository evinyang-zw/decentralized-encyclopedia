# Agent 间协议：实现范围与偏差说明

本文件回答一个问题：**"简化版 A2A"到底简化了什么？**
结论先说：本项目实现的是 **A2A v0.3 JSON-RPC binding 的一个子集**，不是 A2A v1.0 兼容实现；
所有未实现项与偏差列在下表，避免"声称实现规范但细节对不上"。

> 规范现状（2026-11）：A2A 由 Linux Foundation 下的 AAIF 治理，最新稳定版为 **v1.0**
> （2026-03 发布，v1.0.1 补丁）。v1.0 把 JSON-RPC 方法名改为 PascalCase
> （`SendMessage` / `GetTask` / `CancelTask` / `SendStreamingMessage` / `SubscribeToTask`），
> Agent Card 迁到 `/.well-known/agent-card.json` 的 v1.0 结构，并**删除了 `kind` 判别字段**。
> 参考：<https://a2a-protocol.org/latest/specification/>

## 1. 已实现（v0.3 形状）

| 能力 | 实现 | 位置 |
|---|---|---|
| Agent Card 发现 | `GET /.well-known/agent-card.json` 返回 v0.3 形状卡片（name / description / version / protocolVersion / url / preferredTransport / capabilities / defaultInputModes / defaultOutputModes / skills[]） | `src/protocol/server.py`、`src/protocol/models.py` |
| 发消息 | JSON-RPC `message/send`，入参 `{message}`，返回 `Task` | `A2AServer._handle_message_send` |
| 查任务 | `tasks/get`，入参 `{id}`，返回 `Task` | `A2AServer._handle_tasks_get` |
| 取消任务 | `tasks/cancel`，终态任务返回 `-32002` | `A2AServer._handle_tasks_cancel` |
| 任务生命周期 | `submitted → working → completed / failed / canceled / input-required / rejected`；向终态任务发消息返回 `-32004` | `TaskStatus`、`TERMINAL_STATES` |
| 数据模型 | `Part{kind:text/file/data}`、`Message{messageId,role,parts}`、`Task{id,status,history,artifacts}` | `src/protocol/models.py` |
| JSON-RPC 错误 | `-32700/-32600/-32601/-32602/-32603`，任务类 `-32001 TaskNotFound`、`-32002 TaskNotCancelable`、`-32004 UnsupportedOperation` | `src/protocol/server.py` |
| 客户端 | `A2AClient` 支持注入 `http_client`（可用 ASGI 做进程内契约测试），非 2xx 也会解析错误体并抛 `A2AError` | `src/protocol/client.py` |

## 2. 未实现 / 与规范的已知偏差

| 项 | 状态 | 原因 |
|---|---|---|
| 流式 `message/stream`（SSE） | ❌ 未实现 | 当前交互是请求-响应，流式对 5 个数据源查询的收益低于成本；`capabilities.streaming` 如实声明为 `false` |
| Push Notification（webhook） | ❌ 未实现 | 无长任务场景，`capabilities.pushNotifications=false` |
| `tasks/resubscribe` / `tasks/list` / extended card | ❌ 未实现 | 无断线重连、无多租户需求 |
| A2A v1.0 接口 | ❌ 未迁移 | 见下节；迁移成本主要在数据模型与 Card 结构，已列入 Roadmap |
| 认证方案 | 简化：共享 `X-A2A-API-Key` 头 | 规范用 `securitySchemes` 声明多种方案；本地演示用共享 key 足够，README 已标注 |
| 协议级重试 / 幂等 | 由编排层 `Dispatcher` 负责（超时+指数退避重试） | 规范未规定传输层重试语义，放在客户端/编排层更合适 |

## 3. 与 A2A v1.0 的差异（迁移清单）

| # | v1.0 要求 | 本实现 | 迁移动作 |
|---|---|---|---|
| 1 | 方法名 PascalCase（`SendMessage`/`GetTask`/`CancelTask`） | v0.3 风格 `message/send`/`tasks/get`/`tasks/cancel` | 重命名 + 保留旧名别名一版 |
| 2 | Card 增加 `supportedInterfaces[]`（含 `url`/`protocolBinding`/`protocolVersion`） | v0.3 根层 `url` + `protocolVersion` | 结构迁移 |
| 3 | 删除 `Part.kind`，用成员名做判别（`{"text": ...}`） | `Part.kind` + `text`/`data`/`file` | 数据模型迁移（破坏性） |
| 4 | Task 状态 9 个 `TASK_STATE_*`（含 `auth-required`/`unknown`） | 7 个小写状态（缺 `unknown`，含 `rejected`） | 补枚举值 |
| 5 | 请求带 `A2A-Version` 头 | 未带 | 客户端加头，服务端校验 |
| 6 | 官方 TCK / Inspector 一致性验证 | 未跑（仅自建契约测试） | `a2a-tck` JSON-RPC 用例 |

> 结论：**不要对外声称"实现了 A2A 协议"**，准确表述是
> "A2A v0.3 风格的 JSON-RPC 子集（自研编排层）"。

## 4. 怎么验证（30 秒）

```bash
# 1) 启动系统
uv run python scripts/start.py

# 2) 看某個 Agent 的 Agent Card
curl -s localhost:8001/.well-known/agent-card.json | python -m json.tool

# 3) 直接发一条 JSON-RPC message/send
curl -s localhost:8001/ -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0", "id": 1, "method": "message/send",
  "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "Albert Einstein"}]}}
}' | python -m json.tool

# 4) 契约测试（进程内 ASGI，不联网）
uv run pytest tests/test_integration.py tests/test_agent_cards.py -v
```

## 5. 为什么保留自研协议层

- 编排逻辑（路由、并行调度、聚合、降级）本来就不属于协议，放在 `src/orchestrator/`，与协议层解耦；
- 协议层只做三件事：Agent Card 发现、JSON-RPC 任务调用、Task 状态机——对应 `src/protocol/` 的三个文件；
- 这样"协议"可以单独替换（对齐 v1.0 或用官方 SDK），而编排与 5 个数据源适配不受影响。
