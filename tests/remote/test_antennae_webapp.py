"""Test suite for antennae webapp with proper tmux session cleanup."""

import os
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from silica.remote.antennae.config import AntennaeConfig
from silica.remote.antennae.agent_manager import AgentManager


class TestAntennaeConfig:
    """Test antennae configuration management."""

    def test_workspace_name_from_environment(self):
        """Test that workspace name comes from environment variable."""
        with patch.dict(os.environ, {"WORKSPACE_NAME": "test-workspace"}):
            config = AntennaeConfig()
            assert config.get_workspace_name() == "test-workspace"

    def test_workspace_name_default(self):
        """Test default workspace name when not in environment."""
        # Ensure WORKSPACE_NAME is not set
        with patch.dict(os.environ, {}, clear=True):
            config = AntennaeConfig()
            assert config.get_workspace_name() == "agent"

    def test_directory_paths(self):
        """Test directory path configuration."""
        config = AntennaeConfig()
        working_dir = config.get_working_directory()
        code_dir = config.get_code_directory()

        assert code_dir == working_dir / "code"
        assert str(code_dir).endswith("/code")

    def test_tmux_session_name_matches_workspace(self):
        """Test that tmux session name includes workspace name with agent suffix."""
        with patch.dict(os.environ, {"WORKSPACE_NAME": "my-workspace"}):
            config = AntennaeConfig()
            assert config.get_tmux_session_name() == "my-workspace-agent"


class TestAgentManagerSafe:
    """Test agent manager without actually creating tmux sessions."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)

            # Set test workspace environment
            with patch.dict(os.environ, {"WORKSPACE_NAME": "test-workspace"}):
                yield Path(temp_dir)

            os.chdir(original_cwd)

    @pytest.fixture
    def agent_manager(self, temp_workspace):
        """Create agent manager in temporary workspace."""
        return AgentManager()

    def test_workspace_status_no_tmux(self, agent_manager):
        """Test workspace status when no tmux session exists."""
        status = agent_manager.get_workspace_status()

        assert status["workspace_name"] == "test-workspace"
        assert status["tmux_session"]["running"] is False
        assert status["tmux_session"]["info"] is None
        assert "agent_command" in status

    def test_connection_info(self, agent_manager):
        """Test connection info generation."""
        conn_info = agent_manager.get_connection_info()

        assert conn_info["session_name"] == "test-workspace-agent"
        assert conn_info["tmux_running"] is False
        assert "working_directory" in conn_info
        assert "code_directory" in conn_info

    def test_tmux_session_check_no_tmux_installed(self, agent_manager):
        """Test tmux session check when tmux is not installed."""
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            assert agent_manager.is_tmux_session_running() is False

    def test_tmux_session_check_no_session(self, agent_manager):
        """Test tmux session check when no session exists."""
        # Mock subprocess.run to return non-zero exit code (session doesn't exist)
        mock_result = Mock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            assert agent_manager.is_tmux_session_running() is False

    def test_clone_repository_creates_directory(self, agent_manager):
        """Test that clone_repository ensures code directory exists."""
        # Mock git.Repo.clone_from to avoid actual cloning
        with patch("git.Repo.clone_from") as mock_clone:
            result = agent_manager.clone_repository("https://github.com/test/repo.git")

            assert result is True
            assert agent_manager.config.get_code_directory().exists()
            mock_clone.assert_called_once()

    def test_clone_repository_cleans_existing_directory(
        self, agent_manager, temp_workspace
    ):
        """Test that clone_repository cleans existing code directory."""
        # Create existing code directory with files
        code_dir = agent_manager.config.get_code_directory()
        code_dir.mkdir(exist_ok=True)
        test_file = code_dir / "existing_file.txt"
        test_file.write_text("existing content")

        # Mock git.Repo.clone_from
        with patch("git.Repo.clone_from"):
            result = agent_manager.clone_repository("https://github.com/test/repo.git")

            assert result is True
            assert code_dir.exists()
            assert not test_file.exists()  # Should be cleaned

    def test_setup_environment_no_code_directory(self, agent_manager):
        """Test setup_environment fails when code directory doesn't exist."""
        # Explicitly ensure code directory doesn't exist
        code_dir = agent_manager.config.get_code_directory()
        if code_dir.exists():
            import shutil

            shutil.rmtree(code_dir)

        result = agent_manager.setup_environment()
        assert result is False

    def test_setup_environment_uv_not_found(self, agent_manager):
        """Test setup_environment handles uv not being installed."""
        # Create code directory
        agent_manager.config.ensure_code_directory()

        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = agent_manager.setup_environment()
            assert result is False

    def test_cleanup_workspace_no_sessions(self, agent_manager):
        """Test cleanup when no tmux sessions exist."""
        # Mock tmux session as not running
        with patch.object(agent_manager, "is_tmux_session_running", return_value=False):
            result = agent_manager.cleanup_workspace()
            assert result is True


class TestTmuxSessionManagement:
    """Test actual tmux session management with proper cleanup.

    These tests create real tmux sessions but ensure they're cleaned up.
    Only runs if tmux is available.
    """

    def _tmux_available(self) -> bool:
        """Check if tmux is available on the system."""
        try:
            subprocess.run(["tmux", "-V"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _cleanup_test_sessions(self):
        """Clean up any test tmux sessions."""
        try:
            # List all sessions and kill any that start with "test-"
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                sessions = result.stdout.strip().split("\n")
                for session in sessions:
                    if session.startswith("test-"):
                        subprocess.run(
                            ["tmux", "kill-session", "-t", session],
                            capture_output=True,
                            check=False,
                        )
        except FileNotFoundError:
            # tmux not available
            pass

    @pytest.fixture(autouse=True)
    def cleanup_sessions(self):
        """Automatically clean up test sessions before and after each test."""
        # Clean up before test
        self._cleanup_test_sessions()

        yield

        # Clean up after test
        self._cleanup_test_sessions()

    @pytest.mark.skipif(not _tmux_available(None), reason="tmux not available")
    def test_tmux_session_lifecycle(self):
        """Test complete tmux session lifecycle with real tmux."""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)

            try:
                with patch.dict(os.environ, {"WORKSPACE_NAME": "test-tmux-lifecycle"}):
                    agent_manager = AgentManager()

                    # Ensure code directory exists
                    agent_manager.config.ensure_code_directory()

                    # Initially no session
                    assert not agent_manager.is_tmux_session_running()

                    # Start session
                    result = agent_manager.start_tmux_session()
                    assert result is True

                    # Session should now exist
                    assert agent_manager.is_tmux_session_running()

                    # Get session info
                    session_info = agent_manager.get_tmux_session_info()
                    assert session_info is not None
                    assert session_info["session_name"] == "test-tmux-lifecycle-agent"

                    # Starting again should be idempotent (preserve existing session)
                    result = agent_manager.start_tmux_session()
                    assert result is True
                    assert agent_manager.is_tmux_session_running()

                    # Stop session
                    result = agent_manager.stop_tmux_session()
                    assert result is True

                    # Session should be gone
                    assert not agent_manager.is_tmux_session_running()

            finally:
                os.chdir(original_cwd)

    @pytest.mark.skipif(not _tmux_available(None), reason="tmux not available")
    def test_send_message_to_session(self):
        """Test sending messages to tmux session."""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)

            try:
                with patch.dict(os.environ, {"WORKSPACE_NAME": "test-tmux-message"}):
                    agent_manager = AgentManager()
                    agent_manager.config.ensure_code_directory()

                    # Can't send message without session
                    result = agent_manager.send_message_to_session("test message")
                    assert result is False

                    # Start session
                    agent_manager.start_tmux_session()

                    # Now can send message
                    result = agent_manager.send_message_to_session(
                        "echo 'test message'"
                    )
                    assert result is True

            finally:
                os.chdir(original_cwd)

    @pytest.mark.skipif(not _tmux_available(None), reason="tmux not available")
    def test_session_preservation(self):
        """Test that existing sessions are preserved during start_tmux_session."""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)

            try:
                with patch.dict(os.environ, {"WORKSPACE_NAME": "test-tmux-preserve"}):
                    agent_manager = AgentManager()
                    agent_manager.config.ensure_code_directory()

                    # Start first session
                    result = agent_manager.start_tmux_session()
                    assert result is True

                    # Get initial session info
                    initial_info = agent_manager.get_tmux_session_info()
                    assert initial_info is not None

                    # Start "again" - should preserve existing session
                    result = agent_manager.start_tmux_session()
                    assert result is True

                    # Session info should be the same (session preserved)
                    preserved_info = agent_manager.get_tmux_session_info()
                    assert preserved_info is not None
                    assert (
                        preserved_info["session_name"] == initial_info["session_name"]
                    )

            finally:
                os.chdir(original_cwd)


class TestWebAppSafety:
    """Test webapp without actually running servers or creating sessions."""

    @pytest.fixture
    def mock_agent_manager(self):
        """Mock agent manager for webapp testing."""
        mock_manager = Mock()
        mock_manager.get_workspace_status.return_value = {
            "workspace_name": "test-workspace",
            "code_directory": "/test/code",
            "code_directory_exists": False,
            "tmux_session": {"running": False, "info": None},
            "agent_command": "test command",
        }
        mock_manager.get_connection_info.return_value = {
            "session_name": "test-workspace",
            "working_directory": "/test",
            "code_directory": "/test/code",
            "tmux_running": False,
        }
        return mock_manager

    def test_webapp_imports(self):
        """Test that webapp can be imported without side effects."""
        from silica.remote.antennae.webapp import app

        assert app is not None
        assert hasattr(app, "routes")

    def test_webapp_models(self):
        """Test Pydantic models for type safety."""
        from silica.remote.antennae.webapp import (
            InitializeRequest,
            TellRequest,
            StatusResponse,
        )

        # Test InitializeRequest
        req = InitializeRequest(repo_url="https://github.com/test/repo.git")
        assert req.repo_url == "https://github.com/test/repo.git"
        assert req.branch == "main"  # default

        # Test TellRequest
        tell_req = TellRequest(message="test message")
        assert tell_req.message == "test message"

        # Test response models
        status_resp = StatusResponse(
            workspace_name="test",
            code_directory="/test",
            code_directory_exists=True,
            repository={"status": "clean", "is_dirty": False},
            tmux_session={"running": True, "info": None},
            agent_command="test cmd",
        )
        assert status_resp.workspace_name == "test"

    @patch("silica.remote.antennae.webapp.agent_manager")
    def test_webapp_endpoints_safe(self, mock_agent_manager):
        """Test webapp endpoints without creating actual sessions."""
        from fastapi.testclient import TestClient
        from silica.remote.antennae.webapp import app

        # Configure mocks
        mock_agent_manager.get_workspace_status.return_value = {
            "workspace_name": "test-workspace",
            "code_directory": "/test/code",
            "code_directory_exists": False,
            "repository": {"status": "no_code_directory", "is_dirty": False},
            "tmux_session": {"running": False, "info": None},
            "agent_command": "test command",
        }

        mock_agent_manager.get_connection_info.return_value = {
            "session_name": "test-workspace",
            "working_directory": "/test",
            "code_directory": "/test/code",
            "tmux_running": False,
        }

        with patch.dict(os.environ, {"WORKSPACE_NAME": "test-workspace"}):
            client = TestClient(app)

            # Test health endpoint
            response = client.get("/health")
            assert response.status_code == 200

            # Test status endpoint
            response = client.get("/status")
            assert response.status_code == 200

            # Test connect endpoint
            response = client.get("/connect")
            assert response.status_code == 200

        # Test response models
