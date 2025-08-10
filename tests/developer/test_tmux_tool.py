"""Tests for TmuxTool functions."""

import pytest
from unittest.mock import Mock, patch

from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode, DoSomethingElseError
from silica.developer.user_interface import UserInterface
from silica.developer.tools.tmux_tool import (
    tmux_create_session,
    tmux_list_sessions,
    tmux_execute_command,
    tmux_get_output,
    tmux_destroy_session,
    tmux_destroy_all_sessions,
    _check_tmux_available,
    _validate_command_safety,
)


class MockUserInterface(UserInterface):
    """Mock user interface for testing."""

    def __init__(self):
        self.messages = []
        self.permission_responses = {}

    def handle_assistant_message(self, message: str) -> None:
        pass

    def handle_system_message(self, message: str, markdown=True, live=None) -> None:
        self.messages.append(("system", message))

    def permission_callback(
        self, action: str, resource: str, sandbox_mode: SandboxMode, action_arguments
    ):
        key = f"{action}:{resource}"
        return self.permission_responses.get(key, True)

    def permission_rendering_callback(
        self, action: str, resource: str, action_arguments
    ):
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

    def set_permission_response(self, action: str, resource: str, allow: bool):
        """Set response for permission check."""
        self.permission_responses[f"{action}:{resource}"] = allow


class TestTmuxToolHelpers:
    """Test helper functions."""

    @patch("subprocess.run")
    def test_check_tmux_available_success(self, mock_run):
        """Test tmux availability check when tmux is available."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        assert _check_tmux_available() is True

    @patch("subprocess.run")
    def test_check_tmux_available_failure(self, mock_run):
        """Test tmux availability check when tmux is not available."""
        mock_run.side_effect = FileNotFoundError()

        assert _check_tmux_available() is False

    def test_validate_command_safety(self):
        """Test command safety validation."""
        # Safe commands
        assert _validate_command_safety("echo hello") is True
        assert _validate_command_safety("ls -la") is True
        assert _validate_command_safety("python script.py") is True

        # Dangerous commands
        assert _validate_command_safety("sudo rm -rf /") is False
        assert _validate_command_safety("rm -rf --recursive /home") is False
        assert _validate_command_safety("chmod 777 /etc/passwd") is False


class TestTmuxToolFunctions:
    """Test tmux tool functions."""

    def create_test_context(self, permission_responses=None):
        """Create a test context with mock UI."""
        ui = MockUserInterface()
        if permission_responses:
            for action_resource, allow in permission_responses.items():
                action, resource = action_resource.split(":", 1)
                ui.set_permission_response(action, resource, allow)

        return AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=ui,
        )

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    def test_tmux_create_session_no_tmux(self, mock_check_tmux):
        """Test session creation when tmux is not available."""
        mock_check_tmux.return_value = False
        context = self.create_test_context()

        result = tmux_create_session(context, "test_session")

        assert "tmux is not available" in result

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    def test_tmux_create_session_invalid_name(self, mock_check_tmux):
        """Test session creation with invalid name."""
        mock_check_tmux.return_value = True
        context = self.create_test_context()

        result = tmux_create_session(context, "invalid name")

        assert "Invalid session name" in result

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_create_session_success(self, mock_get_manager, mock_check_tmux):
        """Test successful session creation."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.create_session.return_value = (
            True,
            "Session created successfully",
        )
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_create_session(context, "test_session")

        assert "Session created successfully" in result
        mock_manager.create_session.assert_called_once_with("test_session", None)

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_create_session_with_command(self, mock_get_manager, mock_check_tmux):
        """Test session creation with initial command."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.create_session.return_value = (
            True,
            "Session created successfully",
        )
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_create_session(context, "test_session", "echo hello")

        assert "Session created successfully" in result
        mock_manager.create_session.assert_called_once_with(
            "test_session", "echo hello"
        )

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    def test_tmux_create_session_dangerous_command(self, mock_check_tmux):
        """Test session creation with dangerous initial command."""
        mock_check_tmux.return_value = True
        context = self.create_test_context()

        result = tmux_create_session(context, "test_session", "sudo rm -rf /")

        assert "dangerous operations" in result

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_list_sessions_empty(self, mock_get_manager, mock_check_tmux):
        """Test listing sessions when no sessions exist."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.list_sessions.return_value = []
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_list_sessions(context)

        assert "No tmux sessions found" in result

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_list_sessions_with_data(self, mock_get_manager, mock_check_tmux):
        """Test listing sessions with data."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.list_sessions.return_value = [
            {
                "name": "session1",
                "status": "active",
                "created_at": "2023-01-01T10:00:00",
                "last_activity": "2023-01-01T10:05:00",
                "commands_executed": 5,
            },
            {
                "name": "session2",
                "status": "inactive",
                "created_at": "2023-01-01T11:00:00",
                "last_activity": "2023-01-01T11:02:00",
                "commands_executed": 2,
            },
        ]
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_list_sessions(context)

        assert "session1" in result
        assert "session2" in result
        assert "active" in result
        assert "inactive" in result

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_execute_command_success(self, mock_get_manager, mock_check_tmux):
        """Test successful command execution."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.execute_command.return_value = (True, "Command executed")
        mock_manager.capture_session_output.return_value = (True, "output captured")
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_execute_command(context, "test_session", "echo hello")

        assert "Command executed" in result
        assert "output captured" in result
        mock_manager.execute_command.assert_called_once_with(
            "test_session",
            "echo hello",
            timeout=None,
            timeout_action="interrupt",
            refresh_env=False,
        )

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    def test_tmux_execute_command_dangerous(self, mock_check_tmux):
        """Test command execution with dangerous command."""
        mock_check_tmux.return_value = True
        context = self.create_test_context()

        result = tmux_execute_command(context, "test_session", "sudo rm -rf /")

        assert "dangerous operations" in result

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_execute_command_no_capture(self, mock_get_manager, mock_check_tmux):
        """Test command execution without output capture."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.execute_command.return_value = (True, "Command executed")
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_execute_command(
            context, "test_session", "echo hello", capture_output=False
        )

        assert "Command executed" in result
        assert "output captured" not in result
        mock_manager.capture_session_output.assert_not_called()

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_get_output_success(self, mock_get_manager, mock_check_tmux):
        """Test successful output retrieval."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.capture_session_output.return_value = (True, "session output")
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_get_output(context, "test_session", lines=25)

        assert "session output" in result
        assert "Output from session 'test_session'" in result
        mock_manager.capture_session_output.assert_called_once_with("test_session", 25)

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_get_output_failure(self, mock_get_manager, mock_check_tmux):
        """Test output retrieval failure."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.capture_session_output.return_value = (False, "Session not found")
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_get_output(context, "nonexistent_session")

        assert "Error: Session not found" in result

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_destroy_session_success(self, mock_get_manager, mock_check_tmux):
        """Test successful session destruction."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.destroy_session.return_value = (True, "Session destroyed")
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_destroy_session(context, "test_session")

        assert "Session destroyed" in result
        mock_manager.destroy_session.assert_called_once_with("test_session")

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_destroy_all_sessions_success(self, mock_get_manager, mock_check_tmux):
        """Test successful destruction of all sessions."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.list_sessions.return_value = [
            {"name": "session1"},
            {"name": "session2"},
        ]
        mock_manager.destroy_session.side_effect = [
            (True, "Session 1 destroyed"),
            (True, "Session 2 destroyed"),
        ]
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_destroy_all_sessions(context)

        assert "Destroyed 2 sessions" in result
        assert mock_manager.destroy_session.call_count == 2

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_destroy_all_sessions_empty(self, mock_get_manager, mock_check_tmux):
        """Test destruction of all sessions when none exist."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.list_sessions.return_value = []
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_destroy_all_sessions(context)

        assert "No sessions to destroy" in result

    @patch("silica.developer.tools.tmux_tool._check_tmux_available")
    @patch("silica.developer.tools.tmux_tool.get_session_manager")
    def test_tmux_destroy_all_sessions_with_errors(
        self, mock_get_manager, mock_check_tmux
    ):
        """Test destruction with some failures."""
        mock_check_tmux.return_value = True
        mock_manager = Mock()
        mock_manager.list_sessions.return_value = [
            {"name": "session1"},
            {"name": "session2"},
        ]
        mock_manager.destroy_session.side_effect = [
            (True, "Session 1 destroyed"),
            (False, "Session 2 failed"),
        ]
        mock_get_manager.return_value = mock_manager

        context = self.create_test_context()

        result = tmux_destroy_all_sessions(context)

        assert "Destroyed 1 sessions" in result
        assert "Errors:" in result
        assert "Session 2 failed" in result

    def test_permission_denied_create_session(self):
        """Test permission denied for session creation."""
        ui = MockUserInterface()
        ui.set_permission_response("tmux_create_session", "test_session", False)

        context = AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.REQUEST_EVERY_TIME,
            sandbox_contents=[],
            user_interface=ui,
        )

        with patch(
            "silica.developer.tools.tmux_tool._check_tmux_available"
        ) as mock_check:
            mock_check.return_value = True
            result = tmux_create_session(context, "test_session")

        assert "Permission denied" in result

    def test_permission_denied_command_execution(self):
        """Test permission denied for command execution."""
        ui = MockUserInterface()
        ui.set_permission_response("shell", "echo hello", False)

        context = AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.REQUEST_EVERY_TIME,
            sandbox_contents=[],
            user_interface=ui,
        )

        with patch(
            "silica.developer.tools.tmux_tool._check_tmux_available"
        ) as mock_check:
            mock_check.return_value = True
            result = tmux_execute_command(context, "test_session", "echo hello")

        assert "Permission denied" in result

    def test_do_something_else_error(self):
        """Test DoSomethingElseError propagation."""
        context = self.create_test_context()

        # Mock the sandbox to raise DoSomethingElseError
        with patch.object(context.sandbox, "check_permissions") as mock_check:
            mock_check.side_effect = DoSomethingElseError()

            with patch(
                "silica.developer.tools.tmux_tool._check_tmux_available"
            ) as mock_tmux:
                mock_tmux.return_value = True

                with pytest.raises(DoSomethingElseError):
                    tmux_create_session(context, "test_session")


class TestTmuxToolIntegration:
    """Integration tests for tmux tool functions."""

    def create_test_context(self):
        """Create a test context for integration tests."""
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

    def test_full_session_workflow(self):
        """Test complete session workflow with real tmux."""
        context = self.create_test_context()

        # Create session
        result = tmux_create_session(context, "integration_test")
        assert "successfully" in result

        # List sessions
        result = tmux_list_sessions(context)
        assert "integration_test" in result

        # Execute command
        result = tmux_execute_command(context, "integration_test", "echo 'test output'")
        assert "executed" in result

        # Get output
        result = tmux_get_output(context, "integration_test")
        assert "test output" in result or "Output from session" in result

        # Destroy session
        result = tmux_destroy_session(context, "integration_test")
        assert "destroyed" in result or "Session destroyed" in result

    def test_session_with_background_process(self):
        """Test session with a background process."""
        context = self.create_test_context()

        # Create session with background process
        result = tmux_create_session(
            context, "background_test", "sleep 2 && echo 'done'"
        )
        assert "successfully" in result

        try:
            # Execute additional command
            result = tmux_execute_command(
                context, "background_test", "echo 'immediate'"
            )
            assert "executed" in result

            # Get output (should show immediate output)
            result = tmux_get_output(context, "background_test")
            assert "immediate" in result or "Output from session" in result

        finally:
            # Cleanup
            tmux_destroy_session(context, "background_test")
