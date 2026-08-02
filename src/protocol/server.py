"""A2A Server base class — FastAPI wrapper for Agent Card + JSON-RPC."""
from __future__ import annotations
import time
import uuid
from collections import OrderedDict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.protocol.models import (
    AgentCard, Message, Part, Task, TaskState,
    JSONRPCRequest, JSONRPCResponse,
)
from src.protocol.security import A2AAuthMiddleware


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

    def _setup_routes(self):
        @self.app.get("/.well-known/agent.json")
        async def agent_card():
            return self.card.model_dump()

        @self.app.post("/")
        async def handle_rpc(request: Request):
            if not self.auth.authenticate(request):
                return JSONResponse(status_code=401, content={"error": "Unauthorized"})

            body = await request.json()
            req = JSONRPCRequest(**body)

            if req.method == "message/send":
                return await self._handle_message_send(req)
            elif req.method == "task/get":
                return await self._handle_task_get(req)
            elif req.method == "task/cancel":
                return await self._handle_task_cancel(req)
            else:
                return JSONRPCResponse(
                    error={"code": -32601, "message": f"Method not found: {req.method}"},
                    id=req.id,
                ).model_dump()

    async def _handle_message_send(self, req: JSONRPCRequest) -> dict:
        params = req.params
        message = Message(**params.get("message", {}))
        task_id = params.get("task_id", str(uuid.uuid4()))

        if task_id not in self.tasks:
            self.tasks.put(task_id, Task(task_id=task_id, state=TaskState.WORKING))

        task = self.tasks.get(task_id)
        task.messages.append(message)

        try:
            response = await self.handle_message(message, task)
            task.messages.append(response)
            task.state = TaskState.COMPLETED
        except Exception as e:
            task.state = TaskState.FAILED
            response = Message(
                role="agent",
                parts=[Part(type="text", text=f"Error: {e}")],
            )

        return JSONRPCResponse(
            result={"task_id": task_id, "messages": [m.model_dump() for m in task.messages]},
            id=req.id,
        ).model_dump()

    async def _handle_task_get(self, req: JSONRPCRequest) -> dict:
        task_id = req.params.get("task_id", "")
        task = self.tasks.get(task_id)
        if not task:
            return JSONRPCResponse(
                error={"code": -32602, "message": "Task not found"}, id=req.id
            ).model_dump()
        return JSONRPCResponse(result=task.model_dump(), id=req.id).model_dump()

    async def _handle_task_cancel(self, req: JSONRPCRequest) -> dict:
        task_id = req.params.get("task_id", "")
        task = self.tasks.get(task_id)
        if task:
            task.state = TaskState.CANCELED
        return JSONRPCResponse(
            result={"task_id": task_id, "state": "canceled"}, id=req.id
        ).model_dump()

    async def handle_message(self, message: Message, task: Task) -> Message:
        raise NotImplementedError

    def start(self, host: str = "0.0.0.0", port: int = 8001):
        import uvicorn
        uvicorn.run(self.app, host=host, port=port)
