"""Tests for A2A protocol data models (v0.3-style subset)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.protocol.models import (
    TERMINAL_STATES,
    AgentCard,
    JSONRPCRequest,
    JSONRPCResponse,
    Message,
    Part,
    Skill,
    Task,
    TaskState,
    TaskStatus,
)


class TestPart:
    def test_text_part(self):
        p = Part(kind="text", text="hello")
        assert p.kind == "text"
        assert p.text == "hello"

    def test_data_part(self):
        p = Part(kind="data", data={"key": "value"})
        assert p.kind == "data"
        assert p.data == {"key": "value"}

    def test_file_part(self):
        p = Part(kind="file", file={"uri": "http://example.com/f.txt", "mimeType": "text/plain"})
        assert p.kind == "file"
        assert p.file is not None
        assert p.file["uri"] == "http://example.com/f.txt"

    def test_invalid_kind(self):
        with pytest.raises(ValidationError):
            Part(kind="invalid")


class TestMessage:
    def test_user_message(self):
        msg = Message(role="user", parts=[Part(kind="text", text="hi")])
        assert msg.role == "user"
        assert len(msg.parts) == 1
        assert msg.kind == "message"
        assert msg.messageId  # auto-generated, required by the spec

    def test_message_ids_are_unique(self):
        a = Message(role="user", parts=[])
        b = Message(role="user", parts=[])
        assert a.messageId != b.messageId

    def test_agent_message_with_metadata(self):
        msg = Message(
            role="agent",
            parts=[Part(kind="text", text="result")],
            metadata={"task_id": "abc"},
        )
        assert msg.metadata["task_id"] == "abc"


class TestAgentCard:
    def test_agent_card(self):
        card = AgentCard(
            name="TestAgent",
            description="A test agent",
            version="1.0.0",
            url="http://localhost:8001",
            skills=[
                Skill(id="test", name="test", description="test skill", tags=["tag1"]),
            ],
        )
        assert card.name == "TestAgent"
        assert card.protocolVersion == "0.3.0"
        assert card.preferredTransport == "JSONRPC"
        assert card.capabilities["streaming"] is False
        assert card.defaultInputModes == ["text"]
        assert card.skills[0].id == "test"

    def test_skill_requires_id_and_name(self):
        with pytest.raises(ValidationError):
            Skill(name="missing-id")  # type: ignore[call-arg]

    def test_url_required(self):
        with pytest.raises(ValidationError):
            AgentCard(name="NoUrl", version="1.0.0")  # type: ignore[call-arg]


class TestTaskState:
    def test_states(self):
        assert TaskState.SUBMITTED == "submitted"
        assert TaskState.WORKING == "working"
        assert TaskState.COMPLETED == "completed"
        assert TaskState.INPUT_REQUIRED == "input-required"
        assert TaskState.REJECTED == "rejected"

    def test_terminal_states(self):
        assert TaskState.COMPLETED in TERMINAL_STATES
        assert TaskState.FAILED in TERMINAL_STATES
        assert TaskState.CANCELED in TERMINAL_STATES
        assert TaskState.REJECTED in TERMINAL_STATES
        assert TaskState.WORKING not in TERMINAL_STATES
        assert TaskState.INPUT_REQUIRED not in TERMINAL_STATES


class TestTask:
    def test_task_defaults(self):
        task = Task(id="t1")
        assert task.id == "t1"
        assert task.kind == "task"
        assert task.status.state == TaskState.SUBMITTED
        assert task.history == []
        assert task.artifacts == []

    def test_task_status_carries_message(self):
        msg = Message(role="agent", parts=[Part(kind="text", text="done")])
        task = Task(id="t2", status=TaskStatus(state=TaskState.COMPLETED, message=msg))
        assert task.status.state == TaskState.COMPLETED
        assert task.status.message is not None
        assert task.status.message.parts[0].text == "done"
        assert task.status.timestamp  # ISO-8601 timestamp is always set

    def test_state_property(self):
        task = Task(id="t3", status=TaskStatus(state=TaskState.WORKING))
        assert task.state == TaskState.WORKING


class TestJSONRPC:
    def test_request(self):
        req = JSONRPCRequest(method="message/send", id=1, params={"message": {}})
        assert req.jsonrpc == "2.0"

    def test_request_rejects_bad_version(self):
        with pytest.raises(ValidationError):
            JSONRPCRequest(jsonrpc="1.0", method="message/send", id=1)

    def test_response_success(self):
        resp = JSONRPCResponse(result={"status": "ok"}, id=1)
        assert resp.error is None

    def test_response_error(self):
        resp = JSONRPCResponse(error={"code": -1, "message": "fail"}, id=1)
        assert resp.result is None
