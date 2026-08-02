from __future__ import annotations
import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.orchestrator.registry import AgentRegistry
from src.orchestrator.router import Router
from src.orchestrator.dispatcher import Dispatcher
from src.agents.coordinator import Coordinator
from src.protocol.models import Message, Part, Task, TaskState

router = APIRouter()
_registry: AgentRegistry | None = None
_coordinator: Coordinator | None = None


def init_coordinator(registry: AgentRegistry, llm=None):
    global _registry, _coordinator
    _registry = registry
    router_obj = Router(registry=registry, llm=llm)
    dispatcher = Dispatcher(timeout=10.0, max_retries=1)
    _coordinator = Coordinator(registry=registry, router=router_obj, dispatcher=dispatcher, llm=llm)


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/api/agents")
async def list_agents():
    if _registry is None:
        return []
    return [{"name": c.name, "endpoint": c.endpoint, "skills": [s.name for s in c.skills]} for c in _registry.get_all()]


@router.post("/api/query")
async def query(body: dict):
    question = body.get("question", "")
    if not question:
        return JSONResponse(status_code=400, content={"error": "Missing question"})
    if len(question) > 4096:
        return JSONResponse(status_code=400, content={"error": "Question too long (max 4096 chars)"})
    if _coordinator is None:
        return JSONResponse(status_code=503, content={"error": "Coordinator not initialized"})
    msg = Message(role="user", parts=[Part(type="text", text=question)])
    task = Task(task_id=str(uuid.uuid4()), state=TaskState.SUBMITTED)
    task_msg = await _coordinator.handle_message(msg, task)
    return {"answer": task_msg.parts[0].text if task_msg.parts else "", "process": []}
