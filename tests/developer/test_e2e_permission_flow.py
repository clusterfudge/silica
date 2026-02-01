"""End-to-end permission flow test.

This test verifies the complete permission flow:
1. Coordinator spawns worker
2. Worker attempts operation requiring permission
3. Coordinator receives permission request
4. Coordinator grants permission
5. Worker receives response and proceeds
"""

import pytest
import threading
import time
from unittest.mock import patch

from deadrop import Deaddrop

from silica.developer.coordination.session import (
    CoordinationSession,
    AgentState,
)
from silica.developer.coordination.client import CoordinationContext
from silica.developer.coordination import (
    TaskAssign,
    TaskAck,
    Result,
    PermissionRequest,
    PermissionResponse,
)
from silica.developer.coordination.worker_permissions import (
    create_worker_permission_callback,
    setup_worker_sandbox_permissions,
)
from silica.developer.tools.coordination import (
    set_current_session,
    grant_permission,
    list_pending_permissions,
    grant_queued_permission,
)
from silica.developer.tools.worker_coordination import (
    set_worker_context,
    check_inbox,
    send_to_coordinator,
)
from silica.developer.sandbox import Sandbox, SandboxMode


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
def coordinator_session(deaddrop, temp_sessions_dir):
    """Create a coordinator session."""
    session = CoordinationSession.create_session(deaddrop, "E2E Test Coordinator")
    set_current_session(session)
    yield session
    set_current_session(None)


@pytest.fixture
def worker_setup(deaddrop, coordinator_session):
    """Set up a worker with coordination context."""
    # Create worker identity
    worker_identity = deaddrop.create_identity(
        ns=coordinator_session.namespace_id,
        display_name="Test Worker",
        ns_secret=coordinator_session.namespace_secret,
    )

    # Register in coordinator's agent registry
    coordinator_session.register_agent(
        agent_id="worker-1",
        identity_id=worker_identity["id"],
        display_name="Test Worker",
        workspace_name="test-workspace",
    )
    coordinator_session.add_agent_to_room("worker-1")
    coordinator_session.update_agent_state("worker-1", AgentState.IDLE)

    # Create worker context
    worker_context = CoordinationContext(
        deaddrop=deaddrop,
        namespace_id=coordinator_session.namespace_id,
        namespace_secret=coordinator_session.namespace_secret,
        identity_id=worker_identity["id"],
        identity_secret=worker_identity["secret"],
        room_id=coordinator_session.state.room_id,
        coordinator_id=coordinator_session.state.coordinator_id,
    )

    # Set up worker tools
    set_worker_context(worker_context, "worker-1")

    yield {
        "context": worker_context,
        "identity": worker_identity,
        "agent_id": "worker-1",
    }

    # Cleanup
    set_worker_context(None, None)


class TestE2EPermissionFlow:
    """End-to-end permission flow tests."""

    def test_basic_permission_request_grant(
        self, deaddrop, coordinator_session, worker_setup
    ):
        """Test basic permission request and grant flow.

        1. Worker requests permission
        2. Coordinator receives request
        3. Coordinator grants permission
        4. Worker receives response
        """
        worker_context = worker_setup["context"]
        worker_identity = worker_setup["identity"]

        # Create permission callback with short timeout
        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=10.0,
        )

        # Worker will request permission in a thread
        result_holder = {"result": None, "error": None}

        def worker_request_permission():
            try:
                result_holder["result"] = callback(
                    action="shell",
                    resource="rm -rf /tmp/test",
                    sandbox_mode=SandboxMode.REMEMBER_PER_RESOURCE,
                    action_arguments=None,
                    group="Shell",
                )
            except Exception as e:
                result_holder["error"] = str(e)

        # Start worker thread
        worker_thread = threading.Thread(target=worker_request_permission)
        worker_thread.start()

        # Give worker time to send request
        time.sleep(0.2)

        # Coordinator polls for messages
        messages = coordinator_session.context.receive_messages(wait=0)

        # Find permission request
        permission_requests = [
            m for m in messages if isinstance(m.message, PermissionRequest)
        ]
        assert len(permission_requests) == 1

        request = permission_requests[0].message
        assert request.action == "shell"
        assert request.resource == "rm -rf /tmp/test"
        assert request.agent_id == "worker-1"

        # Coordinator grants permission
        response = PermissionResponse(
            request_id=request.request_id,
            decision="allow",
            reason="Test approval",
        )
        coordinator_session.context.send_message(worker_identity["id"], response)

        # Wait for worker to receive response
        worker_thread.join(timeout=5.0)

        # Verify worker got permission
        assert result_holder["error"] is None
        assert result_holder["result"] is True

    def test_permission_deny(self, deaddrop, coordinator_session, worker_setup):
        """Test permission denial flow."""
        worker_context = worker_setup["context"]
        worker_identity = worker_setup["identity"]

        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=10.0,
        )

        result_holder = {"result": None}

        def worker_request():
            result_holder["result"] = callback(
                action="shell",
                resource="rm -rf /",
                sandbox_mode=SandboxMode.REMEMBER_PER_RESOURCE,
                action_arguments=None,
                group="Shell",
            )

        worker_thread = threading.Thread(target=worker_request)
        worker_thread.start()

        time.sleep(0.2)

        # Get request
        messages = coordinator_session.context.receive_messages(wait=0)
        request = [m for m in messages if isinstance(m.message, PermissionRequest)][
            0
        ].message

        # Deny permission
        response = PermissionResponse(
            request_id=request.request_id,
            decision="deny",
            reason="Too dangerous",
        )
        coordinator_session.context.send_message(worker_identity["id"], response)

        worker_thread.join(timeout=5.0)

        assert result_holder["result"] is False

    def test_permission_timeout(self, deaddrop, coordinator_session, worker_setup):
        """Test permission timeout (no response from coordinator)."""
        worker_context = worker_setup["context"]

        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=0.5,  # Very short timeout
        )

        start = time.time()
        result = callback(
            action="shell",
            resource="some_command",
            sandbox_mode=SandboxMode.REMEMBER_PER_RESOURCE,
            action_arguments=None,
            group="Shell",
        )
        elapsed = time.time() - start

        # Should timeout and return False
        assert result is False
        assert elapsed >= 0.4

    def test_always_tool_permission(self, deaddrop, coordinator_session, worker_setup):
        """Test granting permanent tool permission."""
        worker_context = worker_setup["context"]
        worker_identity = worker_setup["identity"]

        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=10.0,
        )

        result_holder = {"result": None}

        def worker_request():
            result_holder["result"] = callback(
                action="read_file",
                resource="/some/file",
                sandbox_mode=SandboxMode.REMEMBER_PER_RESOURCE,
                action_arguments=None,
                group="Files",
            )

        worker_thread = threading.Thread(target=worker_request)
        worker_thread.start()

        time.sleep(0.2)

        messages = coordinator_session.context.receive_messages(wait=0)
        request = [m for m in messages if isinstance(m.message, PermissionRequest)][
            0
        ].message

        # Grant always_tool permission
        response = PermissionResponse(
            request_id=request.request_id,
            decision="always_tool",
        )
        coordinator_session.context.send_message(worker_identity["id"], response)

        worker_thread.join(timeout=5.0)

        assert result_holder["result"] == "always_tool"

    def test_sandbox_integration(
        self, deaddrop, coordinator_session, worker_setup, tmp_path
    ):
        """Test permission flow integrated with sandbox."""
        worker_context = worker_setup["context"]
        worker_identity = worker_setup["identity"]

        # Create sandbox with worker permission callback
        sandbox = Sandbox(
            root_directory=str(tmp_path),
            mode=SandboxMode.REQUEST_EVERY_TIME,
        )

        setup_worker_sandbox_permissions(
            sandbox=sandbox,
            context=worker_context,
            agent_id="worker-1",
            timeout=10.0,
        )

        # Worker checks permission through sandbox in a thread
        result_holder = {"result": None}

        def worker_check():
            result_holder["result"] = sandbox.check_permissions(
                action="write_file",
                resource="/test.txt",
                group="Files",
            )

        worker_thread = threading.Thread(target=worker_check)
        worker_thread.start()

        time.sleep(0.2)

        # Coordinator receives and grants
        messages = coordinator_session.context.receive_messages(wait=0)
        request = [m for m in messages if isinstance(m.message, PermissionRequest)][
            0
        ].message

        response = PermissionResponse(
            request_id=request.request_id,
            decision="allow",
        )
        coordinator_session.context.send_message(worker_identity["id"], response)

        worker_thread.join(timeout=5.0)

        assert result_holder["result"] is True


class TestE2ECoordinatorTools:
    """Test coordinator permission tools in E2E scenario."""

    def test_grant_permission_tool(self, deaddrop, coordinator_session, worker_setup):
        """Test the grant_permission coordinator tool."""
        worker_context = worker_setup["context"]
        worker_setup["identity"]

        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=10.0,
        )

        result_holder = {"result": None}

        def worker_request():
            result_holder["result"] = callback(
                action="shell",
                resource="ls -la",
                sandbox_mode=SandboxMode.REMEMBER_PER_RESOURCE,
                action_arguments=None,
                group="Shell",
            )

        worker_thread = threading.Thread(target=worker_request)
        worker_thread.start()

        time.sleep(0.2)

        # Get request
        messages = coordinator_session.context.receive_messages(wait=0)
        request = [m for m in messages if isinstance(m.message, PermissionRequest)][
            0
        ].message

        # Use coordinator tool to grant
        grant_result = grant_permission(
            request_id=request.request_id,
            decision="allow",
            agent_id="worker-1",
        )

        # Check for success indicator
        assert "✓" in grant_result or "Sent" in grant_result

        worker_thread.join(timeout=5.0)

        assert result_holder["result"] is True


class TestE2EPermissionQueue:
    """Test permission queue in E2E scenario."""

    def test_timeout_then_grant_later(
        self, deaddrop, coordinator_session, worker_setup
    ):
        """Test: worker times out, coordinator grants later via queue."""
        worker_context = worker_setup["context"]

        # Very short timeout - will definitely timeout
        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=0.3,
            queue_on_timeout=True,
        )

        # Worker requests and times out
        result = callback(
            action="shell",
            resource="important_command",
            sandbox_mode=SandboxMode.REMEMBER_PER_RESOURCE,
            action_arguments=None,
            group="Shell",
        )

        # Should have timed out
        assert result is False

        # Coordinator should have received the request
        messages = coordinator_session.context.receive_messages(wait=0)
        requests = [m for m in messages if isinstance(m.message, PermissionRequest)]
        assert len(requests) >= 1

        # Queue it manually (simulating what coordinator would do)
        request = requests[0].message
        coordinator_session.queue_permission(
            request_id=request.request_id,
            agent_id=request.agent_id,
            action=request.action,
            resource=request.resource,
            context=request.context,
        )

        # Coordinator can see pending permissions
        pending_result = list_pending_permissions()
        assert "shell" in pending_result
        assert "important_command" in pending_result

        # Coordinator grants queued permission
        grant_result = grant_queued_permission(request.request_id, "allow")
        assert "granted" in grant_result.lower()

        # Permission status should be updated
        pending = coordinator_session.get_pending_permission(request.request_id)
        assert pending.status == "granted"


class TestE2EFullWorkflow:
    """Test complete coordinator-worker workflow with permissions."""

    def test_task_with_permission_request(
        self, deaddrop, coordinator_session, worker_setup
    ):
        """Test full workflow: task assignment → permission request → completion."""
        worker_context = worker_setup["context"]
        worker_identity = worker_setup["identity"]

        # 1. Worker checks inbox and gets task
        # (Coordinator sends task)
        task = TaskAssign(
            task_id="task-1",
            description="Delete temporary files",
            context="Clean up /tmp/test directory",
        )
        coordinator_session.context.send_message(worker_identity["id"], task)

        # Worker receives task
        inbox_result = check_inbox()
        assert "task-1" in inbox_result
        assert "Delete temporary files" in inbox_result

        # 2. Worker acknowledges
        ack_result = send_to_coordinator("ack", task_id="task-1")
        assert "Sent" in ack_result

        # Coordinator receives ack
        messages = coordinator_session.context.receive_messages(wait=0.5)
        acks = [m for m in messages if isinstance(m.message, TaskAck)]
        assert len(acks) >= 1

        # 3. Worker needs permission for operation
        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=5.0,
        )

        result_holder = {"permission": None}

        def request_permission():
            result_holder["permission"] = callback(
                action="shell",
                resource="rm -rf /tmp/test",
                sandbox_mode=SandboxMode.REMEMBER_PER_RESOURCE,
                action_arguments=None,
                group="Shell",
            )

        perm_thread = threading.Thread(target=request_permission)
        perm_thread.start()

        time.sleep(0.2)

        # 4. Coordinator grants permission
        messages = coordinator_session.context.receive_messages(wait=0)
        perm_requests = [
            m for m in messages if isinstance(m.message, PermissionRequest)
        ]
        assert len(perm_requests) >= 1

        request = perm_requests[0].message
        response = PermissionResponse(
            request_id=request.request_id,
            decision="allow",
        )
        coordinator_session.context.send_message(worker_identity["id"], response)

        perm_thread.join(timeout=5.0)
        assert result_holder["permission"] is True

        # 5. Worker sends result
        result = send_to_coordinator(
            "result",
            status="complete",
            summary="Deleted temp files successfully",
            data={"files_deleted": 5},
        )
        assert "Sent" in result

        # 6. Coordinator receives result
        messages = coordinator_session.context.receive_messages(wait=0.5)
        results = [m for m in messages if isinstance(m.message, Result)]
        assert len(results) >= 1
        assert results[0].message.status == "complete"
