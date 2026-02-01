"""Tests for worker permission handling via deaddrop coordination."""

import pytest
import threading
import time
from unittest.mock import patch

from deadrop import Deaddrop

from silica.developer.coordination.session import CoordinationSession
from silica.developer.coordination.client import CoordinationContext
from silica.developer.coordination import (
    PermissionRequest,
    PermissionResponse,
)
from silica.developer.coordination.worker_permissions import (
    create_worker_permission_callback,
    create_worker_permission_rendering_callback,
    setup_worker_sandbox_permissions,
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
    """Create a coordinator session for testing."""
    return CoordinationSession.create_session(deaddrop, "Test Coordinator")


@pytest.fixture
def worker_context(deaddrop, coordinator_session):
    """Create a worker context connected to the coordinator."""
    # Create worker identity
    worker_identity = deaddrop.create_identity(
        ns=coordinator_session.namespace_id,
        display_name="Test Worker",
        ns_secret=coordinator_session.namespace_secret,
    )

    return CoordinationContext(
        deaddrop=deaddrop,
        namespace_id=coordinator_session.namespace_id,
        namespace_secret=coordinator_session.namespace_secret,
        identity_id=worker_identity["id"],
        identity_secret=worker_identity["secret"],
        room_id=coordinator_session.state.room_id,
        coordinator_id=coordinator_session.state.coordinator_id,
    )


class TestCreateWorkerPermissionCallback:
    """Test the worker permission callback factory."""

    def test_creates_callback(self, worker_context):
        """Should create a callable permission callback."""
        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=1.0,
        )

        assert callable(callback)

    def test_callback_sends_permission_request(
        self, worker_context, coordinator_session
    ):
        """Should send PermissionRequest to coordinator."""
        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=0.5,  # Short timeout for test
        )

        # Call callback in a thread since it will block
        result_holder = {"result": None}

        def call_callback():
            result_holder["result"] = callback(
                action="shell",
                resource="ls -la",
                sandbox_mode=SandboxMode.ALLOW_ALL,
                action_arguments=None,
                group="Shell",
            )

        thread = threading.Thread(target=call_callback)
        thread.start()

        # Give time for request to be sent
        time.sleep(0.1)

        # Check coordinator received the request
        messages = coordinator_session.context.receive_messages(wait=0)
        request_messages = [
            m for m in messages if isinstance(m.message, PermissionRequest)
        ]

        # Thread will timeout and return False
        thread.join(timeout=2.0)

        assert len(request_messages) == 1
        assert request_messages[0].message.action == "shell"
        assert request_messages[0].message.resource == "ls -la"
        assert result_holder["result"] is False  # Timed out

    def test_callback_returns_allow_on_allow_response(
        self, worker_context, coordinator_session, deaddrop
    ):
        """Should return True when coordinator allows."""
        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=5.0,
        )

        result_holder = {"result": None, "request_id": None}

        def call_callback():
            result_holder["result"] = callback(
                action="read_file",
                resource="/etc/passwd",
                sandbox_mode=SandboxMode.ALLOW_ALL,
                action_arguments=None,
                group="Files",
            )

        thread = threading.Thread(target=call_callback)
        thread.start()

        # Give time for request to be sent
        time.sleep(0.1)

        # Get the request
        messages = coordinator_session.context.receive_messages(wait=0)
        request_messages = [
            m for m in messages if isinstance(m.message, PermissionRequest)
        ]
        assert len(request_messages) == 1
        request_id = request_messages[0].message.request_id

        # Send allow response
        response = PermissionResponse(
            request_id=request_id,
            decision="allow",
        )
        coordinator_session.context.send_message(worker_context.identity_id, response)

        # Wait for callback to complete
        thread.join(timeout=2.0)

        assert result_holder["result"] is True

    def test_callback_returns_deny_on_deny_response(
        self, worker_context, coordinator_session, deaddrop
    ):
        """Should return False when coordinator denies."""
        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=5.0,
        )

        result_holder = {"result": None}

        def call_callback():
            result_holder["result"] = callback(
                action="shell",
                resource="rm -rf /",
                sandbox_mode=SandboxMode.ALLOW_ALL,
                action_arguments=None,
                group="Shell",
            )

        thread = threading.Thread(target=call_callback)
        thread.start()

        # Give time for request to be sent
        time.sleep(0.1)

        # Get the request and respond with deny
        messages = coordinator_session.context.receive_messages(wait=0)
        request_messages = [
            m for m in messages if isinstance(m.message, PermissionRequest)
        ]
        request_id = request_messages[0].message.request_id

        response = PermissionResponse(
            request_id=request_id,
            decision="deny",
            reason="Dangerous operation",
        )
        coordinator_session.context.send_message(worker_context.identity_id, response)

        thread.join(timeout=2.0)

        assert result_holder["result"] is False

    def test_callback_returns_always_tool(
        self, worker_context, coordinator_session, deaddrop
    ):
        """Should return 'always_tool' when coordinator allows permanently."""
        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=5.0,
        )

        result_holder = {"result": None}

        def call_callback():
            result_holder["result"] = callback(
                action="read_file",
                resource="/some/file",
                sandbox_mode=SandboxMode.ALLOW_ALL,
                action_arguments=None,
                group="Files",
            )

        thread = threading.Thread(target=call_callback)
        thread.start()

        time.sleep(0.1)

        messages = coordinator_session.context.receive_messages(wait=0)
        request_messages = [
            m for m in messages if isinstance(m.message, PermissionRequest)
        ]
        request_id = request_messages[0].message.request_id

        response = PermissionResponse(
            request_id=request_id,
            decision="always_tool",
        )
        coordinator_session.context.send_message(worker_context.identity_id, response)

        thread.join(timeout=2.0)

        assert result_holder["result"] == "always_tool"

    def test_callback_timeout(self, worker_context, coordinator_session):
        """Should return False on timeout."""
        callback = create_worker_permission_callback(
            context=worker_context,
            agent_id="worker-1",
            timeout=0.5,  # Short timeout
        )

        start = time.time()
        result = callback(
            action="shell",
            resource="some_command",
            sandbox_mode=SandboxMode.ALLOW_ALL,
            action_arguments=None,
            group="Shell",
        )
        elapsed = time.time() - start

        # Should have timed out
        assert result is False
        assert elapsed >= 0.4  # Should have waited at least close to timeout


class TestCreateWorkerPermissionRenderingCallback:
    """Test the rendering callback factory."""

    def test_creates_noop_callback(self):
        """Should create a no-op callback."""
        callback = create_worker_permission_rendering_callback()

        # Should not raise and return None
        result = callback("read_file", "/some/path", None)
        assert result is None


class TestSetupWorkerSandboxPermissions:
    """Test sandbox configuration for workers."""

    def test_configures_sandbox(self, worker_context, tmp_path):
        """Should configure sandbox with worker callbacks."""
        sandbox = Sandbox(
            root_directory=str(tmp_path),
            mode=SandboxMode.REMEMBER_PER_RESOURCE,
        )

        # Store original callbacks
        original_permission = sandbox._permission_check_callback
        original_rendering = sandbox._permission_check_rendering_callback

        # Configure for worker
        setup_worker_sandbox_permissions(
            sandbox=sandbox,
            context=worker_context,
            agent_id="worker-1",
            timeout=60.0,
        )

        # Callbacks should be replaced
        assert sandbox._permission_check_callback is not original_permission
        assert sandbox._permission_check_rendering_callback is not original_rendering

        # New callbacks should be callable
        assert callable(sandbox._permission_check_callback)
        assert callable(sandbox._permission_check_rendering_callback)


class TestWorkerBootstrapIntegration:
    """Test integration with worker bootstrap."""

    def test_setup_worker_sandbox_via_bootstrap(
        self, deaddrop, temp_sessions_dir, tmp_path
    ):
        """Should be able to set up sandbox via bootstrap module."""
        from silica.developer.coordination.worker_bootstrap import (
            WorkerBootstrapResult,
            setup_worker_sandbox_permissions as bootstrap_setup,
        )

        # Create coordinator session
        session = CoordinationSession.create_session(deaddrop, "Test")

        # Create worker identity
        worker_identity = deaddrop.create_identity(
            ns=session.namespace_id,
            display_name="Worker",
            ns_secret=session.namespace_secret,
        )

        context = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=session.namespace_id,
            namespace_secret=session.namespace_secret,
            identity_id=worker_identity["id"],
            identity_secret=worker_identity["secret"],
            room_id=session.state.room_id,
            coordinator_id=session.state.coordinator_id,
        )

        result = WorkerBootstrapResult(
            context=context,
            agent_id="test-worker-1",
            display_name="Test Worker",
            namespace_id=session.namespace_id,
            room_id=session.state.room_id,
            coordinator_id=session.state.coordinator_id,
        )

        # Create sandbox
        sandbox = Sandbox(
            root_directory=str(tmp_path),
            mode=SandboxMode.REMEMBER_PER_RESOURCE,
        )

        # Configure via bootstrap function
        bootstrap_setup(sandbox, result, timeout=30.0)

        # Verify configuration
        assert callable(sandbox._permission_check_callback)
