"""Tests for A2A protocol data models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.protocol.models import (
    Part, Message, Skill, AgentCard, TaskState, Task,
    JSONRPCRequest, JSONRPCResponse,
)


class TestPart:
    def test_text_part(self):
        p = Part(type="text", text="hello")
        assert p.type == "text"
        assert p.text == "hello"

    def test_data_part(self):
        p = Part(type="data", data={"key": "value"})
        assert p.type == "data"
        assert p.data == {"key": "value"}

    def test_file_part(self):
        p = Part(type="file", file_uri="http://example.com/f.txt", mime_type="text/plain")
        assert p.type == "file"
        assert p.file_uri == "http://example.com/f.txt"

    def test_invalid_type(self):
        with pytest.raises(ValidationError):
            Part(type="invalid")


class TestMessage:
    def test_user_message(self):
        msg = Message(role="user", parts=[Part(type="text", text="hi")])
        assert msg.role == "user"
        assert len(msg.parts) == 1

    def test_agent_message_with_metadata(self):
        msg = Message(
            role="agent",
            parts=[Part(type="text", text="result")],
            metadata={"task_id": "abc"},
        )
        assert msg.metadata["task_id"] == "abc"


class TestAgentCard:
    def test_agent_card(self):
        card = AgentCard(
            name="TestAgent",
            description="A test agent",
            version="1.0.0",
            skills=[Skill(name="test", description="test skill", input_schema={}, output_schema={})],
            endpoint="http://localhost:8001",
        )
        assert card.name == "TestAgent"
        assert card.transport == "jsonrpc"
        assert card.capabilities["streaming"] is False


class TestTaskState:
    def test_states(self):
        assert TaskState.SUBMITTED == "submitted"
        assert TaskState.WORKING == "working"
        assert TaskState.COMPLETED == "completed"
        assert TaskState.FAILED == "failed"


class TestTask:
    def test_task(self):
        task = Task(task_id="t1", state=TaskState.SUBMITTED)
        assert task.task_id == "t1"
        assert task.messages == []


class TestJSONRPC:
    def test_request(self):
        req = JSONRPCRequest(method="message/send", id=1, params={"message": {}})
        assert req.jsonrpc == "2.0"

    def test_response_success(self):
        resp = JSONRPCResponse(result={"status": "ok"}, id=1)
        assert resp.error is None

    def test_response_error(self):
        resp = JSONRPCResponse(error={"code": -1, "message": "fail"}, id=1)
        assert resp.result is None
