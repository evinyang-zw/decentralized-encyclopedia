"""A2A server base class — FastAPI wrapper for Agent Card + JSON-RPC.

Implements a subset of the A2A **v0.3** JSON-RPC binding:
    GET  /.well-known/agent-card.json   -> AgentCard
    POST /  (JSON-RPC 2.0)
        message/send   -> Task
        tasks/get      -> Task
        tasks/cancel   -> Task

Not implemented (documented in docs/protocol.md): streaming (`message/stream`),
push notifications, `tasks/resubscribe`, extended agent card, and the A2A v1.0
PascalCase/`supportedInterfaces` shape.
"""
from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.protocol.models import (
    TASK_NOT_CANCELABLE,
    TASK_NOT_FOUND,
    TERMINAL_STATES,
    UNSUPPORTED_OPERATION,
    AgentCard,
    JSONRPCRequest,
    JSONRPCResponse,
    Message,
    Task,
    TaskState,
    TaskStatus,
)
from src.protocol.security import A2AAuthMiddleware

CARD_PATH = "/.well-known/agent-card.json"

# JSON-RPC 2.0 reserved error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def rpc_result(result: dict[str, Any], req_id: int | str | None) -> dict[str, Any]:
    return JSONRPCResponse(result=result, id=req_id).model_dump(exclude_none=True)


def rpc_error(
    code: int, message: str, req_id: int | str | None, data: Any = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return JSONRPCResponse(error=error, id=req_id).model_dump(exclude_none=True)


class TaskStore:
    """Bounded task store with TTL-based eviction."""

    def __init__(self, max_size: int = 1000, ttl_seconds: float = 3600.0):
        self._tasks: OrderedDict[str, tuple[Task, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds

    def get(self, task_id: str) -> Task | None:
        entry = self._tasks.get(task_id)
        if entry is None:
            return None
        task, created_at = entry
        if time.monotonic() - created_at > self._ttl:
            self._tasks.pop(task_id, None)
            return None
        return task

    def put(self, task_id: str, task: Task) -> None:
        self._tasks[task_id] = (task, time.monotonic())
        if len(self._tasks) > self._max_size:
            self._tasks.popitem(last=False)

    def __contains__(self, task_id: str) -> bool:
        return self.get(task_id) is not None


class A2AServer:
    def __init__(self, card: AgentCard, api_key: str | None = None):
        self.card = card
        self.auth = A2AAuthMiddleware(api_key)
        self.app = FastAPI()
        self.tasks = TaskStore()
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.get(CARD_PATH)
        async def agent_card() -> dict[str, Any]:
            return self.card.model_dump()

        @self.app.post("/")
        async def handle_rpc(request: Request) -> Any:
            if not self.auth.authenticate(request):
                return JSONResponse(
                    status_code=401,
                    content=rpc_error(INVALID_REQUEST, "Unauthorized", None),
                )
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    status_code=400,
                    content=rpc_error(PARSE_ERROR, "Parse error", None),
                )
            try:
                req = JSONRPCRequest(**body)
            except Exception as exc:
                req_id = body.get("id") if isinstance(body, dict) else None
                return JSONResponse(
                    status_code=400,
                    content=rpc_error(INVALID_REQUEST, f"Invalid request: {exc}", req_id),
                )

            if req.method == "message/send":
                return await self._handle_message_send(req)
            if req.method == "tasks/get":
                return self._handle_tasks_get(req)
            if req.method == "tasks/cancel":
                return self._handle_tasks_cancel(req)
            return JSONResponse(
                status_code=200,
                content=rpc_error(METHOD_NOT_FOUND, f"Method not found: {req.method}", req.id),
            )

    # ------------------------------------------------------------ handlers
    async def _handle_message_send(self, req: JSONRPCRequest) -> dict[str, Any]:
        params = req.params
        raw_message = params.get("message")
        if not isinstance(raw_message, dict):
            return rpc_error(INVALID_PARAMS, "params.message is required", req.id)
        try:
            message = Message(**raw_message)
        except Exception as exc:
            return rpc_error(INVALID_PARAMS, f"Invalid message: {exc}", req.id)

        task_id = message.taskId or str(uuid.uuid4())
        task = self.tasks.get(task_id)
        if task is None:
            task = Task(id=task_id, contextId=message.contextId or task_id)
            self.tasks.put(task_id, task)
        elif task.status.state in TERMINAL_STATES:
            return rpc_error(
                UNSUPPORTED_OPERATION,
                f"Task {task_id} is in terminal state {task.status.state.value}",
                req.id,
            )

        task.history.append(message)
        task.status = TaskStatus(state=TaskState.WORKING)
        try:
            response = await self.handle_message(message, task)
        except Exception as exc:  # surface a failed task, never a 200 with garbage
            error_message = Message(role="agent", parts=[], metadata={"error": str(exc)})
            task.status = TaskStatus(state=TaskState.FAILED, message=error_message)
            return rpc_result(task.model_dump(), req.id)

        task.history.append(response)
        task.status = TaskStatus(state=TaskState.COMPLETED, message=response)
        return rpc_result(task.model_dump(), req.id)

    def _handle_tasks_get(self, req: JSONRPCRequest) -> dict[str, Any]:
        task_id = req.params.get("id") or req.params.get("taskId") or req.params.get("task_id")
        task = self.tasks.get(task_id) if task_id else None
        if task is None:
            return rpc_error(TASK_NOT_FOUND, f"Task not found: {task_id}", req.id)
        return rpc_result(task.model_dump(), req.id)

    def _handle_tasks_cancel(self, req: JSONRPCRequest) -> dict[str, Any]:
        task_id = req.params.get("id") or req.params.get("taskId") or req.params.get("task_id")
        task = self.tasks.get(task_id) if task_id else None
        if task is None:
            return rpc_error(TASK_NOT_FOUND, f"Task not found: {task_id}", req.id)
        if task.status.state in TERMINAL_STATES:
            return rpc_error(
                TASK_NOT_CANCELABLE,
                f"Task {task_id} is not cancelable in state {task.status.state.value}",
                req.id,
            )
        task.status = TaskStatus(state=TaskState.CANCELED)
        return rpc_result(task.model_dump(), req.id)

    # ------------------------------------------------------------ overridable
    async def handle_message(self, message: Message, task: Task) -> Message:
        raise NotImplementedError

    def start(self, host: str = "0.0.0.0", port: int = 8001) -> None:
        import uvicorn

        uvicorn.run(self.app, host=host, port=port)
