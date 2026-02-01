"""Tests for coordination message protocol."""

import pytest
from silica.developer.coordination.protocol import (
    MessageType,
    TaskAssign,
    TaskAck,
    Progress,
    Result,
    PermissionRequest,
    PermissionResponse,
    Idle,
    Question,
    Answer,
    Terminate,
    serialize_message,
    deserialize_message,
    COORDINATION_CONTENT_TYPE,
)


class TestMessageTypes:
    """Test message type enum."""

    def test_message_types_are_strings(self):
        """All message types should be string values."""
        assert MessageType.TASK_ASSIGN.value == "task_assign"
        assert MessageType.RESULT.value == "result"
        assert MessageType.PERMISSION_REQUEST.value == "permission_request"


class TestTaskAssign:
    """Test TaskAssign message."""

    def test_create_task_assign(self):
        msg = TaskAssign(
            task_id="task-123",
            description="Research competitor pricing",
            context={"budget": 1000},
            deadline="2024-12-31T23:59:59Z",
        )
        assert msg.type == "task_assign"
        assert msg.task_id == "task-123"
        assert msg.context == {"budget": 1000}

    def test_roundtrip(self):
        original = TaskAssign(
            task_id="task-456",
            description="Analyze data",
            context={"source": "api"},
        )
        serialized = serialize_message(original)
        restored = deserialize_message(serialized)

        assert isinstance(restored, TaskAssign)
        assert restored.task_id == original.task_id
        assert restored.description == original.description
        assert restored.context == original.context


class TestTaskAck:
    """Test TaskAck message."""

    def test_create_task_ack(self):
        msg = TaskAck(task_id="task-123", agent_id="agent-1")
        assert msg.type == "task_ack"
        assert msg.acknowledged_at  # Should have default timestamp

    def test_roundtrip(self):
        original = TaskAck(task_id="task-789", agent_id="worker-2")
        serialized = serialize_message(original)
        restored = deserialize_message(serialized)

        assert isinstance(restored, TaskAck)
        assert restored.task_id == original.task_id
        assert restored.agent_id == original.agent_id


class TestProgress:
    """Test Progress message."""

    def test_create_progress(self):
        msg = Progress(
            task_id="task-123",
            agent_id="agent-1",
            progress=0.5,
            message="Halfway done",
        )
        assert msg.type == "progress"
        assert msg.progress == 0.5

    def test_roundtrip(self):
        original = Progress(
            task_id="task-123",
            agent_id="agent-1",
            progress=0.75,
            message="Almost there",
        )
        serialized = serialize_message(original)
        restored = deserialize_message(serialized)

        assert isinstance(restored, Progress)
        assert restored.progress == 0.75
        assert restored.message == "Almost there"


class TestResult:
    """Test Result message."""

    def test_create_result_success(self):
        msg = Result(
            task_id="task-123",
            agent_id="agent-1",
            status="complete",
            data={"findings": ["a", "b", "c"]},
            summary="Found 3 items",
        )
        assert msg.type == "result"
        assert msg.status == "complete"
        assert msg.error is None

    def test_create_result_failed(self):
        msg = Result(
            task_id="task-123",
            agent_id="agent-1",
            status="failed",
            error="Connection timeout",
        )
        assert msg.status == "failed"
        assert msg.error == "Connection timeout"

    def test_roundtrip(self):
        original = Result(
            task_id="task-123",
            agent_id="agent-1",
            status="partial",
            data={"partial_results": [1, 2, 3]},
            summary="Got partial data",
        )
        serialized = serialize_message(original)
        restored = deserialize_message(serialized)

        assert isinstance(restored, Result)
        assert restored.status == "partial"
        assert restored.data == {"partial_results": [1, 2, 3]}


class TestPermissionRequest:
    """Test PermissionRequest message."""

    def test_create_permission_request(self):
        msg = PermissionRequest(
            request_id="perm-123",
            task_id="task-456",
            agent_id="agent-1",
            action="shell_execute",
            resource="curl https://api.example.com",
            context="Need to fetch API data",
        )
        assert msg.type == "permission_request"
        assert msg.action == "shell_execute"

    def test_roundtrip(self):
        original = PermissionRequest(
            request_id="perm-456",
            task_id="task-789",
            agent_id="agent-2",
            action="write_file",
            resource="/tmp/output.txt",
            context="Saving results",
        )
        serialized = serialize_message(original)
        restored = deserialize_message(serialized)

        assert isinstance(restored, PermissionRequest)
        assert restored.action == "write_file"
        assert restored.resource == "/tmp/output.txt"


class TestPermissionResponse:
    """Test PermissionResponse message."""

    def test_create_allow(self):
        msg = PermissionResponse(
            request_id="perm-123",
            decision="allow",
        )
        assert msg.type == "permission_response"
        assert msg.decision == "allow"

    def test_create_deny_with_reason(self):
        msg = PermissionResponse(
            request_id="perm-123",
            decision="deny",
            reason="Dangerous operation",
        )
        assert msg.decision == "deny"
        assert msg.reason == "Dangerous operation"

    def test_roundtrip(self):
        original = PermissionResponse(
            request_id="perm-789",
            decision="timeout",
            reason="No response within 5 minutes",
        )
        serialized = serialize_message(original)
        restored = deserialize_message(serialized)

        assert isinstance(restored, PermissionResponse)
        assert restored.decision == "timeout"


class TestIdle:
    """Test Idle message."""

    def test_create_idle(self):
        msg = Idle(agent_id="agent-1", completed_task_id="task-123")
        assert msg.type == "idle"
        assert msg.available_since  # Should have default timestamp

    def test_roundtrip(self):
        original = Idle(agent_id="agent-2")
        serialized = serialize_message(original)
        restored = deserialize_message(serialized)

        assert isinstance(restored, Idle)
        assert restored.agent_id == "agent-2"


class TestQuestion:
    """Test Question message."""

    def test_create_question(self):
        msg = Question(
            question_id="q-123",
            task_id="task-456",
            agent_id="agent-1",
            question="Should I include historical data?",
            options=["yes", "no", "last 6 months only"],
        )
        assert msg.type == "question"
        assert len(msg.options) == 3

    def test_roundtrip(self):
        original = Question(
            question_id="q-456",
            task_id="task-789",
            agent_id="agent-2",
            question="Which format?",
            options=["JSON", "CSV"],
        )
        serialized = serialize_message(original)
        restored = deserialize_message(serialized)

        assert isinstance(restored, Question)
        assert restored.options == ["JSON", "CSV"]


class TestAnswer:
    """Test Answer message."""

    def test_create_answer(self):
        msg = Answer(
            question_id="q-123",
            task_id="task-456",
            answer="last 6 months only",
            context="We're focused on recent trends",
        )
        assert msg.type == "answer"
        assert msg.answer == "last 6 months only"

    def test_roundtrip(self):
        original = Answer(
            question_id="q-456",
            task_id="task-789",
            answer="JSON",
        )
        serialized = serialize_message(original)
        restored = deserialize_message(serialized)

        assert isinstance(restored, Answer)
        assert restored.answer == "JSON"


class TestTerminate:
    """Test Terminate message."""

    def test_create_terminate(self):
        msg = Terminate(reason="Task cancelled by user")
        assert msg.type == "terminate"
        assert msg.reason == "Task cancelled by user"

    def test_roundtrip(self):
        original = Terminate(reason="Shutting down")
        serialized = serialize_message(original)
        restored = deserialize_message(serialized)

        assert isinstance(restored, Terminate)
        assert restored.reason == "Shutting down"


class TestDeserialization:
    """Test deserialization edge cases."""

    def test_deserialize_from_dict(self):
        """Should accept dict directly."""
        data = {"type": "idle", "agent_id": "test-agent"}
        msg = deserialize_message(data)
        assert isinstance(msg, Idle)
        assert msg.agent_id == "test-agent"

    def test_unknown_type_raises(self):
        """Should raise for unknown message types."""
        with pytest.raises(ValueError, match="Unknown message type"):
            deserialize_message({"type": "unknown_type"})

    def test_missing_type_raises(self):
        """Should raise if type field is missing."""
        with pytest.raises(ValueError, match="missing 'type' field"):
            deserialize_message({"agent_id": "test"})


class TestContentType:
    """Test content type constant."""

    def test_content_type_defined(self):
        assert COORDINATION_CONTENT_TYPE == "application/vnd.silica.coordination+json"
