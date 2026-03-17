"""Tests for worker coordination tools."""

import pytest
from unittest.mock import patch

from deadrop import Deaddrop

from silica.developer.coordination import (
    CoordinationContext,
    TaskAssign,
    PermissionResponse,
    Terminate,
)
from silica.developer.coordination.session import CoordinationSession
from silica.developer.tools.worker_coordination import (
    set_worker_context,
    get_worker_context,
    get_worker_agent_id,
    set_current_task,
    get_current_task,
    check_inbox,
    send_to_coordinator,
    broadcast_status,
    mark_idle,
    request_permission,
    request_permission_async,
)


@pytest.fixture
def deaddrop():
    """Create an in-memory deaddrop for testing."""
    return Deaddrop.in_memory()


@pytest.fixture
def temp_sessions_dir(tmp_path):
    """Use a temporary directory for session storage."""
    sessions_dir = tmp_path / "coordination"
    sessions_dir.mkdir()
    with patch(
        "silica.developer.coordination.session.get_sessions_dir",
        return_value=sessions_dir,
    ):
        yield sessions_dir


@pytest.fixture
def coordination_setup(deaddrop, temp_sessions_dir):
    """Set up a full coordination environment with coordinator and worker."""
    # Create coordinator session
    session = CoordinationSession.create_session(deaddrop, "Test Session")

    # Create worker identity
    worker_identity = deaddrop.create_identity(
        ns=session.namespace_id,
        display_name="Worker-1",
        ns_secret=session.namespace_secret,
    )

    # Register worker in session
    session.register_agent(
        agent_id="worker-1",
        identity_id=worker_identity["id"],
        display_name="Worker-1",
        workspace_name="worker-1-project",
    )

    # Add worker to room
    session.add_agent_to_room("worker-1")

    # Create worker context
    worker_ctx = CoordinationContext(
        deaddrop=deaddrop,
        namespace_id=session.namespace_id,
        namespace_secret=session.namespace_secret,
        identity_id=worker_identity["id"],
        identity_secret=worker_identity["secret"],
        room_id=session.state.room_id,
        coordinator_id=session.state.coordinator_id,
    )

    # Set up worker context
    set_worker_context(worker_ctx, "worker-1")
    set_current_task(None)

    yield {
        "session": session,
        "worker_context": worker_ctx,
        "worker_identity": worker_identity,
        "deaddrop": deaddrop,
    }

    # Clean up
    set_worker_context(None, None)


class TestWorkerContextManagement:
    """Test worker context setup."""

    def test_get_context_without_setup_raises(self):
        """Should raise if context not set."""
        set_worker_context(None, None)
        with pytest.raises(RuntimeError, match="Not running as a coordinated worker"):
            get_worker_context()

    def test_set_and_get_context(self, coordination_setup):
        """Should be able to get context after setup."""
        ctx = get_worker_context()
        assert ctx is not None
        assert get_worker_agent_id() == "worker-1"

    def test_task_tracking(self, coordination_setup):
        """Should track current task."""
        assert get_current_task() is None
        set_current_task("task-123")
        assert get_current_task() == "task-123"
        set_current_task(None)
        assert get_current_task() is None


class TestCheckInbox:
    """Test check_inbox tool."""

    def test_check_inbox_empty(self, coordination_setup):
        """Should return no messages when inbox empty."""
        result = check_inbox()
        assert "No new messages" in result

    def test_check_inbox_task_message(self, coordination_setup):
        """Should receive task assignment from coordinator."""
        session = coordination_setup["session"]

        # Coordinator sends task
        task = TaskAssign(
            task_id="task-456",
            description="Do something useful",
            context={"key": "value"},
        )
        session.context.send_message(
            coordination_setup["worker_identity"]["id"],
            task,
        )

        # Worker checks inbox
        result = check_inbox()

        assert "1 new message" in result
        assert "task_assign" in result
        assert "task-456" in result
        assert "Do something useful" in result

    def test_check_inbox_permission_response(self, coordination_setup):
        """Should receive permission response."""
        session = coordination_setup["session"]

        response = PermissionResponse(
            request_id="worker-1-perm-123",
            decision="allow",
            reason="Approved",
        )
        session.context.send_message(
            coordination_setup["worker_identity"]["id"],
            response,
        )

        result = check_inbox()

        assert "permission_response" in result
        assert "allow" in result
        assert "Approved" in result

    def test_check_inbox_terminate_message(self, coordination_setup):
        """Should receive termination request."""
        session = coordination_setup["session"]

        terminate = Terminate(reason="Shutting down")
        session.context.send_message(
            coordination_setup["worker_identity"]["id"],
            terminate,
        )

        result = check_inbox()

        assert "TERMINATION" in result
        assert "Shutting down" in result


class TestSendToCoordinator:
    """Test send_to_coordinator tool."""

    def test_send_ack(self, coordination_setup):
        """Should send task acknowledgment."""
        set_current_task("task-789")

        result = send_to_coordinator("ack", task_id="task-789")

        assert "✓" in result
        assert "ack" in result

        # Coordinator should receive it
        session = coordination_setup["session"]
        messages = session.context.receive_messages(include_room=False)
        assert len(messages) == 1
        assert messages[0].message.type == "task_ack"

    def test_send_progress(self, coordination_setup):
        """Should send progress update."""
        set_current_task("task-100")

        result = send_to_coordinator(
            "progress",
            progress=0.5,
            message="Halfway done",
        )

        assert "✓" in result

        session = coordination_setup["session"]
        messages = session.context.receive_messages(include_room=False)
        assert len(messages) == 1
        assert messages[0].message.type == "progress"
        assert messages[0].message.progress == 0.5

    def test_send_result(self, coordination_setup):
        """Should send task result."""
        set_current_task("task-200")

        result = send_to_coordinator(
            "result",
            status="complete",
            summary="All done!",
            data={"findings": [1, 2, 3]},
        )

        assert "✓" in result

        session = coordination_setup["session"]
        messages = session.context.receive_messages(include_room=False)
        assert len(messages) == 1
        assert messages[0].message.type == "result"
        assert messages[0].message.status == "complete"

        # Current task should be cleared
        assert get_current_task() is None

    def test_send_question(self, coordination_setup):
        """Should send question to coordinator."""
        result = send_to_coordinator(
            "question",
            question="Should I continue?",
            options=["yes", "no"],
        )

        assert "✓" in result

        session = coordination_setup["session"]
        messages = session.context.receive_messages(include_room=False)
        assert len(messages) == 1
        assert messages[0].message.type == "question"
        assert "continue" in messages[0].message.question

    def test_send_unknown_type(self, coordination_setup):
        """Should reject unknown message type."""
        result = send_to_coordinator("unknown_type")
        assert "❌" in result
        assert "Unknown message type" in result


class TestSendToCoordinatorFrameworkIntegration:
    """Test send_to_coordinator when called through the tool framework.

    The framework passes AgentContext as the first positional argument
    to all tool functions. These tests verify the tool handles that
    correctly.
    """

    def test_framework_style_call_with_context_object(self, coordination_setup):
        """Framework injects context object as first arg.

        This is how invoke_tool calls tools:
            tool_func(context, **converted_args)
        """
        set_current_task("task-fw-1")

        class FakeAgentContext:
            pass

        result = send_to_coordinator(
            FakeAgentContext(),
            message_type="result",
            summary="Framework-style result",
            task_id="task-fw-1",
            status="complete",
        )

        assert "✓" in result
        assert "result" in result

        session = coordination_setup["session"]
        messages = session.context.receive_messages(include_room=False)
        assert len(messages) == 1
        assert messages[0].message.summary == "Framework-style result"
        assert messages[0].message.status == "complete"

    def test_framework_style_with_type_kwarg(self, coordination_setup):
        """Claude sometimes sends 'type' instead of 'message_type'.

        This happens because the worker persona examples use 'type'
        in their documentation.
        """
        set_current_task("task-fw-2")

        class FakeAgentContext:
            pass

        # Simulate: {"type": "result", "summary": "...", ...}
        result = send_to_coordinator(
            FakeAgentContext(),
            type="result",
            summary="Morning briefing content",
            task_id="task-fw-2",
            status="complete",
            data={"weather": "sunny"},
        )

        assert "✓" in result

        session = coordination_setup["session"]
        messages = session.context.receive_messages(include_room=False)
        assert len(messages) == 1
        assert messages[0].message.summary == "Morning briefing content"

    def test_framework_check_inbox_with_context(self, coordination_setup):
        """check_inbox should work when framework passes context."""

        class FakeAgentContext:
            pass

        result = check_inbox(FakeAgentContext())
        assert "No new messages" in result

    def test_framework_mark_idle_with_context(self, coordination_setup):
        """mark_idle should work when framework passes context."""
        set_current_task("task-fw-3")

        class FakeAgentContext:
            pass

        result = mark_idle(FakeAgentContext())
        assert "✓" in result
        assert get_current_task() is None

    def test_framework_broadcast_status_with_context(self, coordination_setup):
        """broadcast_status should work when framework passes context."""
        set_current_task("task-fw-4")

        class FakeAgentContext:
            pass

        result = broadcast_status(FakeAgentContext(), message="Working on it")
        assert "✓" in result


class TestBroadcastStatus:
    """Test broadcast_status tool."""

    def test_broadcast_status(self, coordination_setup):
        """Should broadcast to coordination room."""
        set_current_task("task-300")

        result = broadcast_status("Making progress!", progress=0.75)

        assert "✓" in result
        assert "Broadcast" in result

        # Check room messages
        session = coordination_setup["session"]
        deaddrop = coordination_setup["deaddrop"]

        room_messages = deaddrop.get_room_messages(
            ns=session.namespace_id,
            room_id=session.state.room_id,
            secret=session.state.coordinator_secret,
        )

        assert len(room_messages) >= 1


class TestMarkIdle:
    """Test mark_idle tool."""

    def test_mark_idle(self, coordination_setup):
        """Should broadcast idle status."""
        set_current_task("task-400")

        result = mark_idle()

        assert "✓" in result
        assert "idle" in result

        # Current task should be cleared
        assert get_current_task() is None


class TestRequestPermission:
    """Test permission request tools."""

    def test_request_permission_allowed(self, coordination_setup):
        """Should receive allow decision."""
        import threading

        session = coordination_setup["session"]

        # Coordinator will respond in a separate thread
        def coordinator_respond():
            import time

            time.sleep(0.1)  # Small delay
            # Get the request
            messages = session.context.receive_messages(include_room=False)
            if messages:
                request = messages[0].message
                # Send response
                response = PermissionResponse(
                    request_id=request.request_id,
                    decision="allow",
                )
                session.context.send_message(
                    coordination_setup["worker_identity"]["id"],
                    response,
                )

        thread = threading.Thread(target=coordinator_respond)
        thread.start()

        # Worker requests permission
        decision = request_permission(
            action="shell_execute",
            resource="ls -la",
            reason="Need to list files",
            timeout=5,
        )

        thread.join()

        assert decision == "allow"

    def test_request_permission_timeout(self, coordination_setup):
        """Should return timeout if no response."""
        # No coordinator response
        decision = request_permission(
            action="shell_execute",
            resource="rm -rf /",
            reason="Testing timeout",
            timeout=1,  # Short timeout
        )

        assert decision == "timeout"

    def test_request_permission_async(self, coordination_setup):
        """Should send request without blocking."""
        result = request_permission_async(
            action="write_file",
            resource="/tmp/test.txt",
            reason="Need to save data",
        )

        assert "✓" in result
        assert "Permission request sent" in result

        # Coordinator should receive request
        session = coordination_setup["session"]
        messages = session.context.receive_messages(include_room=False)
        assert len(messages) == 1
        assert messages[0].message.type == "permission_request"
