"""A2A protocol data models — v0.3-style JSON-RPC subset.

Scope note: this project implements a *subset* of the A2A **v0.3** wire format
(Agent Card discovery + `message/send` / `tasks/get` / `tasks/cancel`).
A2A v1.0 (released 2026-03) renamed these JSON-RPC methods to PascalCase
(`SendMessage` / `GetTask` / `CancelTask`), moved the card to
`/.well-known/agent-card.json` v1.0 shape, and removed the `kind`
discriminator; this implementation has **not** migrated yet.
See `docs/protocol.md` for the implemented / unimplemented table.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- JSON-RPC errors
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002
PUSH_NOTIFICATION_NOT_SUPPORTED = -32003
UNSUPPORTED_OPERATION = -32004
CONTENT_TYPE_NOT_SUPPORTED = -32005


class A2AError(Exception):
    """Raised when a remote agent answers with a JSON-RPC error object."""

    def __init__(self, code: int, message: str, data: Any | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.data = data


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------- data model
class Part(BaseModel):
    """A2A v0.3 Part — discriminated by ``kind``."""

    kind: Literal["text", "file", "data"] = "text"
    text: str | None = None
    data: Any | None = None
    file: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    kind: Literal["message"] = "message"
    messageId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "agent"]
    parts: list[Part]
    contextId: str | None = None
    taskId: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Skill(BaseModel):
    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    """A2A v0.3 Agent Card (subset of fields; extra fields are ignored)."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    protocolVersion: str = "0.3.0"
    url: str
    preferredTransport: Literal["JSONRPC", "HTTP+JSON"] = "JSONRPC"
    capabilities: dict[str, bool] = Field(
        default_factory=lambda: {"streaming": False, "pushNotifications": False}
    )
    defaultInputModes: list[str] = Field(default_factory=lambda: ["text"])
    defaultOutputModes: list[str] = Field(default_factory=lambda: ["text", "data"])
    skills: list[Skill] = Field(default_factory=list)
    securitySchemes: dict[str, Any] = Field(default_factory=dict)
    security: list[dict[str, Any]] = Field(default_factory=list)


class TaskState(StrEnum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    REJECTED = "rejected"


TERMINAL_STATES: frozenset[TaskState] = frozenset(
    {TaskState.COMPLETED, TaskState.CANCELED, TaskState.FAILED, TaskState.REJECTED}
)


class TaskStatus(BaseModel):
    state: TaskState = TaskState.SUBMITTED
    message: Message | None = None
    timestamp: str = Field(default_factory=_now)


class Task(BaseModel):
    kind: Literal["task"] = "task"
    id: str
    contextId: str | None = None
    status: TaskStatus = Field(default_factory=TaskStatus)
    history: list[Message] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def state(self) -> TaskState:
        return self.status.state


class JSONRPCRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: int | str | None = None


class JSONRPCResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    id: int | str | None = None
