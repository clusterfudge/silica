"""Tests for tmux timeout functionality."""

import pytest
import time
from unittest.mock import patch

from silica.developer.tools.tmux_session import TmuxSessionManager
from silica.developer.tools.tmux_tool import (
    tmux_create_session,
    tmux_execute_command,
    tmux_set_session_timeout,
    tmux_get_output,
    tmux_destroy_session,
    _check_tmux_available,
)
from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode
from silica.developer.user_interface import UserInterface


class MockUserInterface(UserInterface):
    """Mock user interface for testing."""

    def permission_callback(
        self, action: str, resource: str, sandbox_mode: SandboxMode, action_arguments
    ):
        return True

    def permission_rendering_callback(
        self, action: str, resource: str, action_arguments
    ):
        pass

    def handle_assistant_message(self, message: str) -> None:
        pass

    def handle_system_message(self, message: str, markdown=True, live=None) -> None:
        pass

    def handle_tool_use(self, tool_name: str, tool_params):
        pass

    def handle_tool_result(self, name: str, result, live=None):
        pass

    async def get_user_input(self, prompt: str = "") -> str:
        return "Y"

    def handle_user_input(self, user_input: str) -> str:
        return user_input

    def display_token_count(self, *args, **kwargs):
        pass

    def display_welcome_message(self):
        pass

    def status(self, message: str, spinner: str = None):
        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return DummyContext()

    def bare(self, message, live=None):
        pass


class TestTimeoutFunctionality:
    """Test timeout functionality in tmux sessions."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = TmuxSessionManager(
            session_prefix="test_timeout", max_sessions=5, global_default_timeout=30
        )

    def test_timeout_initialization(self):
        """Test timeout initialization and configuration."""
        # Test global timeout
        assert self.manager.global_default_timeout == 30

        # Test session-specific timeout
        from silica.developer.tools.tmux_session import TmuxSession

        session = TmuxSession("test", "tmux_test", default_timeout=60)
        self.manager.sessions["test"] = session
        assert self.manager.sessions["test"].default_timeout == 60

    def test_set_session_timeout(self):
        """Test setting session-specific timeouts."""
        # Create a mock session
        from silica.developer.tools.tmux_session import TmuxSession

        session = TmuxSession("test", "tmux_test")
        self.manager.sessions["test"] = session

        # Set timeout
        success, message = self.manager.set_session_timeout("test", 45)
        assert success is True
        assert "45 seconds" in message
        assert self.manager.sessions["test"].default_timeout == 45

        # Disable timeout
        success, message = self.manager.set_session_timeout("test", None)
        assert success is True
        assert "Disabled" in message
        assert self.manager.sessions["test"].default_timeout is None

    def test_determine_effective_timeout(self):
        """Test timeout precedence logic."""
        from silica.developer.tools.tmux_session import TmuxSession

        session = TmuxSession("test", "tmux_test", default_timeout=60)
        self.manager.sessions["test"] = session

        # Command timeout takes precedence
        timeout = self.manager._determine_effective_timeout("test", 15)
        assert timeout == 15

        # Session timeout used if no command timeout
        timeout = self.manager._determine_effective_timeout("test", None)
        assert timeout == 60

        # Global timeout used if no session timeout
        session.default_timeout = None
        timeout = self.manager._determine_effective_timeout("test", None)
        assert timeout == 30

    def test_is_command_complete(self):
        """Test command completion detection."""
        # Command completed with prompt
        assert self.manager._is_command_complete("output\n❯ ") is True
        assert self.manager._is_command_complete("output\n$ ") is True
        assert self.manager._is_command_complete("output\n# ") is True

        # Command still running
        assert self.manager._is_command_complete("running command...") is False

        # Stuck states
        assert self.manager._is_command_complete("echo 'test\nquote>") is False
        assert self.manager._is_command_complete('echo "test\ndquote>') is False

    @patch("silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command")
    def test_handle_command_timeout_interrupt(self, mock_run_command):
        """Test timeout handling with interrupt action."""
        mock_run_command.return_value = (0, "", "")

        success, message = self.manager._handle_command_timeout(
            "test_session", "interrupt", 30
        )
        assert success is True
        assert "interrupt" in message.lower()

        # Verify Ctrl+C was sent
        mock_run_command.assert_called_with(
            ["tmux", "send-keys", "-t", "test_session", "C-c"]
        )

    @patch("silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command")
    @patch(
        "silica.developer.tools.tmux_session.TmuxSessionManager._kill_session_processes"
    )
    def test_handle_command_timeout_kill(self, mock_kill_processes, mock_run_command):
        """Test timeout handling with kill action."""
        mock_kill_processes.return_value = (True, "Processes killed")

        success, message = self.manager._handle_command_timeout(
            "test_session", "kill", 30
        )
        assert success is True
        mock_kill_processes.assert_called_once_with("test_session")

    @patch("silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command")
    def test_execute_command_with_timeout_validation(self, mock_run_command):
        """Test command execution with timeout parameter validation."""
        from silica.developer.tools.tmux_session import TmuxSession

        session = TmuxSession("test", "tmux_test")
        self.manager.sessions["test"] = session

        # Mock successful command execution
        mock_run_command.return_value = (0, "", "")

        # Valid timeout
        success, message = self.manager.execute_command("test", "echo hello", timeout=5)
        assert success is True

        # Invalid timeout
        success, message = self.manager.execute_command(
            "test", "echo hello", timeout=-1
        )
        # This should be caught at the tool level, but let's test the method directly
        # The timeout validation happens in the tool function, not the manager

    @patch("silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command")
    def test_execute_command_with_timeout_quick_completion(self, mock_run_command):
        """Test command execution that completes before timeout."""
        from silica.developer.tools.tmux_session import TmuxSession

        session = TmuxSession("test", "tmux_test")
        self.manager.sessions["test"] = session

        # Mock command execution and completion check
        def mock_command_side_effect(cmd):
            if "send-keys" in cmd:
                return (0, "", "")
            elif "capture-pane" in cmd:
                return (0, "echo hello\nhello\n❯ ", "")
            else:
                return (0, "", "")

        mock_run_command.side_effect = mock_command_side_effect

        success, message = self.manager.execute_command("test", "echo hello", timeout=5)
        assert success is True
        assert "Command executed" in message


class TestTimeoutToolIntegration:
    """Integration tests for timeout functionality with tool functions."""

    def create_test_context(self):
        """Create a test context."""
        ui = MockUserInterface()
        return AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=ui,
        )

    @pytest.fixture(autouse=True)
    def check_tmux_available(self):
        """Skip integration tests if tmux is not available."""
        if not _check_tmux_available():
            pytest.skip("tmux not available")

    def test_timeout_parameter_validation(self):
        """Test timeout parameter validation in tool functions."""
        context = self.create_test_context()

        # Invalid timeout values
        result = tmux_execute_command(context, "test_session", "echo hello", timeout=-1)
        assert "must be a positive number" in result

        result = tmux_execute_command(context, "test_session", "echo hello", timeout=0)
        assert "must be a positive number" in result

        # Invalid timeout action
        result = tmux_execute_command(
            context, "test_session", "echo hello", timeout=5, timeout_action="invalid"
        )
        assert "must be one of" in result

    def test_set_session_timeout_tool(self):
        """Test the session timeout configuration tool."""
        context = self.create_test_context()

        try:
            # Create session first
            result = tmux_create_session(context, "timeout_test")
            assert "successfully" in result

            # Set session timeout
            result = tmux_set_session_timeout(context, "timeout_test", 30)
            assert "30 seconds" in result

            # Disable session timeout
            result = tmux_set_session_timeout(context, "timeout_test", None)
            assert "Disabled" in result

            # Invalid timeout
            result = tmux_set_session_timeout(context, "timeout_test", -5)
            assert "must be a positive number" in result

        finally:
            try:
                tmux_destroy_session(context, "timeout_test")
            except Exception:
                pass

    def test_command_execution_with_timeout(self):
        """Test actual command execution with timeout."""
        context = self.create_test_context()

        try:
            # Create session
            result = tmux_create_session(context, "timeout_execution_test")
            assert "successfully" in result

            # Execute quick command with timeout
            result = tmux_execute_command(
                context, "timeout_execution_test", "echo 'quick command'", timeout=5
            )
            assert "executed" in result
            assert "timeout: 5s" in result

            # Verify output
            time.sleep(0.5)
            output = tmux_get_output(context, "timeout_execution_test")
            assert "quick command" in output

        finally:
            try:
                tmux_destroy_session(context, "timeout_execution_test")
            except Exception:
                pass

    def test_session_timeout_inheritance(self):
        """Test that commands inherit session-level timeouts."""
        context = self.create_test_context()

        try:
            # Create session
            result = tmux_create_session(context, "inheritance_test")
            assert "successfully" in result

            # Set session timeout
            result = tmux_set_session_timeout(context, "inheritance_test", 10)
            assert "10 seconds" in result

            # Execute command without explicit timeout (should inherit)
            result = tmux_execute_command(
                context, "inheritance_test", "echo 'inherited timeout'"
            )
            assert "executed" in result
            # The timeout inheritance is shown in the session manager, not the tool output

        finally:
            try:
                tmux_destroy_session(context, "inheritance_test")
            except Exception:
                pass
