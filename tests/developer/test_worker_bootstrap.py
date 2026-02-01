"""Tests for worker bootstrap module."""

import os
import pytest
from unittest.mock import patch, MagicMock

from deadrop import Deaddrop

from silica.developer.coordination.worker_bootstrap import (
    get_invite_from_env,
    get_agent_id_from_env,
    is_coordinated_worker,
    claim_invite_and_connect,
    setup_worker_tools,
    bootstrap_worker,
    DEADDROP_INVITE_URL,
    COORDINATION_AGENT_ID,
)
from silica.developer.coordination.session import CoordinationSession
from silica.developer.tools.worker_coordination import (
    get_worker_context,
    get_worker_agent_id,
    set_worker_context,
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
def clean_env():
    """Clean coordination environment variables."""
    old_invite = os.environ.pop(DEADDROP_INVITE_URL, None)
    old_agent_id = os.environ.pop(COORDINATION_AGENT_ID, None)
    yield
    # Restore
    if old_invite:
        os.environ[DEADDROP_INVITE_URL] = old_invite
    if old_agent_id:
        os.environ[COORDINATION_AGENT_ID] = old_agent_id


@pytest.fixture
def cleanup_worker_context():
    """Clean up worker context after test."""
    yield
    set_worker_context(None, None)


class TestEnvironmentDetection:
    """Test environment variable detection."""

    def test_get_invite_from_env_missing(self, clean_env):
        """Should return None if env var not set."""
        assert get_invite_from_env() is None

    def test_get_invite_from_env_present(self, clean_env):
        """Should return invite URL if set."""
        os.environ[DEADDROP_INVITE_URL] = "https://example.com/invite/abc123"
        assert get_invite_from_env() == "https://example.com/invite/abc123"

    def test_get_agent_id_from_env(self, clean_env):
        """Should return agent ID if set."""
        assert get_agent_id_from_env() is None
        os.environ[COORDINATION_AGENT_ID] = "worker-42"
        assert get_agent_id_from_env() == "worker-42"

    def test_is_coordinated_worker_false(self, clean_env):
        """Should return False if no invite URL."""
        assert is_coordinated_worker() is False

    def test_is_coordinated_worker_true(self, clean_env):
        """Should return True if invite URL present."""
        os.environ[DEADDROP_INVITE_URL] = "https://example.com/invite/xyz"
        assert is_coordinated_worker() is True


class TestClaimInviteAndConnect:
    """Test the invite claiming and connection flow."""

    def test_claim_invite_no_url_raises(self, clean_env):
        """Should raise if no invite URL provided."""
        with pytest.raises(RuntimeError, match="No invite URL provided"):
            claim_invite_and_connect()

    def test_claim_invite_success(
        self, deaddrop, temp_sessions_dir, clean_env, cleanup_worker_context
    ):
        """Should successfully claim invite and connect."""
        # Create a coordinator session to get a valid invite
        session = CoordinationSession.create_session(deaddrop, "Test Coordinator")

        # Worker claims the invite
        # Note: We mock the Deaddrop class since in-memory deaddrop
        # doesn't have the full invite URL flow
        with patch(
            "silica.developer.coordination.worker_bootstrap.Deaddrop"
        ) as MockDeaddrop:
            mock_dd = MagicMock()
            MockDeaddrop.return_value = mock_dd

            mock_dd.claim_invite.return_value = {
                "identity_id": "worker-id-123",
                "identity_secret": "worker-secret-456",
                "namespace_id": session.namespace_id,
                "namespace_secret": session.namespace_secret,
                "display_name": "Test Worker",
                "room_id": session.state.room_id,
                "coordinator_id": session.state.coordinator_id,
            }

            result = claim_invite_and_connect(
                invite_url="https://example.com/invite/abc"
            )

        assert result.agent_id.startswith("worker-")
        assert result.display_name == "Test Worker"
        assert result.namespace_id == session.namespace_id
        assert result.room_id == session.state.room_id
        assert result.context is not None


class TestSetupWorkerTools:
    """Test worker tool setup."""

    def test_setup_worker_tools(
        self, deaddrop, temp_sessions_dir, cleanup_worker_context
    ):
        """Should configure worker coordination tools."""
        from silica.developer.coordination.client import CoordinationContext
        from silica.developer.coordination.worker_bootstrap import (
            WorkerBootstrapResult,
        )

        # Create a mock bootstrap result
        session = CoordinationSession.create_session(deaddrop, "Test")

        # Create a simple context
        identity = deaddrop.create_identity(
            ns=session.namespace_id,
            display_name="Worker",
            ns_secret=session.namespace_secret,
        )

        context = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=session.namespace_id,
            namespace_secret=session.namespace_secret,
            identity_id=identity["id"],
            identity_secret=identity["secret"],
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

        # Set up tools
        setup_worker_tools(result)

        # Verify tools are configured
        assert get_worker_context() is context
        assert get_worker_agent_id() == "test-worker-1"


class TestBootstrapWorker:
    """Test the full bootstrap flow."""

    def test_bootstrap_worker_not_coordinated(self, clean_env, cleanup_worker_context):
        """Should return None if not a coordinated worker."""
        result = bootstrap_worker()
        assert result is None

    def test_bootstrap_worker_with_invite(
        self, deaddrop, temp_sessions_dir, clean_env, cleanup_worker_context
    ):
        """Should bootstrap when invite provided."""
        session = CoordinationSession.create_session(deaddrop, "Test")

        with patch(
            "silica.developer.coordination.worker_bootstrap.Deaddrop"
        ) as MockDeaddrop:
            mock_dd = MagicMock()
            MockDeaddrop.return_value = mock_dd

            mock_dd.claim_invite.return_value = {
                "identity_id": "worker-id",
                "identity_secret": "worker-secret",
                "namespace_id": session.namespace_id,
                "namespace_secret": session.namespace_secret,
                "display_name": "Worker",
                "room_id": session.state.room_id,
                "coordinator_id": session.state.coordinator_id,
            }

            result = bootstrap_worker(invite_url="https://example.com/invite/test")

            assert result is not None
            assert result.agent_id.startswith("worker-")

            # Tools should be configured
            assert get_worker_agent_id().startswith("worker-")


class TestDataUrlInvite:
    """Test parsing data: URL invites from spawn_agent."""

    def test_parse_data_url_invite(
        self, deaddrop, temp_sessions_dir, clean_env, cleanup_worker_context
    ):
        """Should parse data: URL invites correctly."""
        import json
        import base64
        from silica.developer.coordination.worker_bootstrap import (
            _parse_data_url_invite,
        )

        # Create invite data like spawn_agent does
        invite_data = {
            "namespace_id": "ns-123",
            "namespace_secret": "ns-secret",
            "identity_id": "id-456",
            "identity_secret": "id-secret",
            "room_id": "room-789",
            "coordinator_id": "coord-abc",
        }

        invite_json = json.dumps(invite_data)
        invite_encoded = base64.b64encode(invite_json.encode()).decode()
        invite_url = f"data:application/json;base64,{invite_encoded}"

        # Parse it
        result = _parse_data_url_invite(invite_url)

        assert result["namespace_id"] == "ns-123"
        assert result["identity_id"] == "id-456"
        assert result["room_id"] == "room-789"
        assert result["coordinator_id"] == "coord-abc"

    def test_claim_invite_data_url(
        self, deaddrop, temp_sessions_dir, clean_env, cleanup_worker_context
    ):
        """Should handle data: URL in claim_invite_and_connect."""
        import json
        import base64

        # Create a coordinator session
        session = CoordinationSession.create_session(deaddrop, "Test Coordinator")

        # Create a worker identity
        worker_identity = deaddrop.create_identity(
            ns=session.namespace_id,
            display_name="Test Worker",
            ns_secret=session.namespace_secret,
        )

        # Create invite data like spawn_agent does
        invite_data = {
            "namespace_id": session.namespace_id,
            "namespace_secret": session.namespace_secret,
            "identity_id": worker_identity["id"],
            "identity_secret": worker_identity["secret"],
            "room_id": session.state.room_id,
            "coordinator_id": session.state.coordinator_id,
        }

        invite_json = json.dumps(invite_data)
        invite_encoded = base64.b64encode(invite_json.encode()).decode()
        invite_url = f"data:application/json;base64,{invite_encoded}"

        # Connect using the data URL
        result = claim_invite_and_connect(invite_url=invite_url)

        assert result.namespace_id == session.namespace_id
        assert result.room_id == session.state.room_id
        assert result.coordinator_id == session.state.coordinator_id
        assert result.context is not None

    def test_invalid_data_url_raises(self, clean_env):
        """Should raise for invalid data: URL."""
        from silica.developer.coordination.worker_bootstrap import (
            _parse_data_url_invite,
        )

        with pytest.raises(ValueError, match="Invalid data URL format"):
            _parse_data_url_invite("data:text/plain;base64,abc")

        with pytest.raises(ValueError, match="Invalid data URL format"):
            _parse_data_url_invite("https://example.com/invite")


class TestGetWorkerPersona:
    """Test getting worker persona."""

    def test_get_worker_persona(self):
        """Should return worker persona with correct settings."""
        from silica.developer.coordination.worker_bootstrap import get_worker_persona

        persona = get_worker_persona()

        assert persona.system_block is not None
        assert "text" in persona.system_block
        # Worker persona should mention coordination
        assert (
            "coordinator" in persona.system_block["text"].lower()
            or "coordination" in persona.system_block["text"].lower()
            or "check_inbox" in persona.system_block["text"].lower()
        )


class TestIntegrateWorkerStartup:
    """Test the hdev integration function."""

    def test_integrate_not_coordinated(self, clean_env):
        """Should return None if not a coordinated worker."""
        from silica.developer.coordination.worker_bootstrap import (
            integrate_worker_startup,
        )

        mock_ui = MagicMock()
        result = integrate_worker_startup(mock_ui)
        assert result is None
        # Should not have shown any messages
        mock_ui.handle_system_message.assert_not_called()

    def test_integrate_coordinated_worker(
        self, deaddrop, temp_sessions_dir, clean_env, cleanup_worker_context
    ):
        """Should bootstrap and send Idle when coordinated."""
        import json
        import base64
        from silica.developer.coordination.worker_bootstrap import (
            integrate_worker_startup,
        )

        # Create a coordinator session
        session = CoordinationSession.create_session(deaddrop, "Test Coordinator")

        # Create worker identity
        worker_identity = deaddrop.create_identity(
            ns=session.namespace_id,
            display_name="Worker",
            ns_secret=session.namespace_secret,
        )

        # Set up environment
        invite_data = {
            "namespace_id": session.namespace_id,
            "namespace_secret": session.namespace_secret,
            "identity_id": worker_identity["id"],
            "identity_secret": worker_identity["secret"],
            "room_id": session.state.room_id,
            "coordinator_id": session.state.coordinator_id,
        }
        invite_json = json.dumps(invite_data)
        invite_encoded = base64.b64encode(invite_json.encode()).decode()
        os.environ[DEADDROP_INVITE_URL] = (
            f"data:application/json;base64,{invite_encoded}"
        )
        os.environ[COORDINATION_AGENT_ID] = "test-worker-1"

        # Mock UI
        mock_ui = MagicMock()

        # Mock Deaddrop to return our in-memory instance
        with patch(
            "silica.developer.coordination.worker_bootstrap.Deaddrop",
            return_value=deaddrop,
        ):
            # Integrate
            result = integrate_worker_startup(mock_ui)

        assert result is not None
        assert result.agent_id == "test-worker-1"

        # Should have shown status messages
        assert mock_ui.handle_system_message.call_count >= 2

        # Coordinator should have received the Idle message
        # (Check by polling coordinator's inbox)
        from silica.developer.coordination import Idle

        messages = session.context.receive_messages(wait=0)
        # Filter for Idle messages
        idle_messages = [m for m in messages if isinstance(m.message, Idle)]
        assert len(idle_messages) == 1
        assert idle_messages[0].message.agent_id == "test-worker-1"


class TestTaskExecutionLoop:
    """Test task execution loop helpers."""

    def test_get_worker_initial_prompt(self, deaddrop, temp_sessions_dir):
        """Should generate initial prompt for worker."""
        from silica.developer.coordination.worker_bootstrap import (
            get_worker_initial_prompt,
            WorkerBootstrapResult,
        )
        from silica.developer.coordination.client import CoordinationContext

        # Create a mock bootstrap result
        session = CoordinationSession.create_session(deaddrop, "Test")
        identity = deaddrop.create_identity(
            ns=session.namespace_id,
            display_name="Worker",
            ns_secret=session.namespace_secret,
        )

        context = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=session.namespace_id,
            namespace_secret=session.namespace_secret,
            identity_id=identity["id"],
            identity_secret=identity["secret"],
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

        prompt = get_worker_initial_prompt(result)

        # Should include worker info
        assert "Test Worker" in prompt
        assert "test-worker-1" in prompt

        # Should instruct to check inbox
        assert "check_inbox" in prompt
        assert "task" in prompt.lower()

    def test_create_worker_task_loop_prompt(self):
        """Should create task loop reminder prompt."""
        from silica.developer.coordination.worker_bootstrap import (
            create_worker_task_loop_prompt,
        )

        prompt = create_worker_task_loop_prompt()

        # Should mention key actions
        assert "mark_idle" in prompt
        assert "check_inbox" in prompt
        assert "termination" in prompt.lower()

    def test_handle_worker_termination(
        self, deaddrop, temp_sessions_dir, cleanup_worker_context
    ):
        """Should send termination acknowledgment."""
        from silica.developer.coordination.worker_bootstrap import (
            handle_worker_termination,
            WorkerBootstrapResult,
        )
        from silica.developer.coordination.client import CoordinationContext
        from silica.developer.coordination import Result

        # Create a mock bootstrap result
        session = CoordinationSession.create_session(deaddrop, "Test")
        identity = deaddrop.create_identity(
            ns=session.namespace_id,
            display_name="Worker",
            ns_secret=session.namespace_secret,
        )

        context = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=session.namespace_id,
            namespace_secret=session.namespace_secret,
            identity_id=identity["id"],
            identity_secret=identity["secret"],
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

        mock_ui = MagicMock()

        # Handle termination
        handle_worker_termination(result, mock_ui, reason="Job complete")

        # Should have sent termination acknowledgment to coordinator
        messages = session.context.receive_messages(wait=0)
        result_messages = [m for m in messages if isinstance(m.message, Result)]
        assert len(result_messages) == 1
        assert result_messages[0].message.status == "terminated"

        # Should have shown status message
        mock_ui.handle_system_message.assert_called_once()
