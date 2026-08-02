"""A2A protocol data models."""
from __future__ import annotations
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel


class Part(BaseModel):
    type: Literal["text", "file", "data"]
    text: str | None = None
    data: Any | None = None
    file_uri: str | None = None
    mime_type: str | None = None


class Message(BaseModel):
    role: Literal["user", "agent"]
    parts: list[Part]
    metadata: dict[str, Any] = {}


class Skill(BaseModel):
    name: str
    description: str
    input_schema: dict
    output_schema: dict


class AgentCard(BaseModel):
    name: str
    description: str
    version: str
    skills: list[Skill]
    capabilities: dict = {"streaming": False, "push_notifications": False}
    security: dict = {"methods": ["none"]}
    transport: str = "jsonrpc"
    endpoint: str


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    INPUT_REQUIRED = "input-required"
    CANCELED = "canceled"


class Task(BaseModel):
    task_id: str
    context_id: str | None = None
    state: TaskState = TaskState.SUBMITTED
    messages: list[Message] = []
    artifacts: list[dict] = []


class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict = {}
    id: int | str


class JSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: dict | None = None
    error: dict | None = None
    id: int | str
