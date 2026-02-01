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
