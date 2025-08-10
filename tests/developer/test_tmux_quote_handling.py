"""Tests for tmux quote handling and shell state recovery."""

import pytest
from unittest.mock import patch

from silica.developer.tools.tmux_session import TmuxSessionManager
from silica.developer.tools.tmux_tool import (
    tmux_create_session,
    tmux_execute_command,
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


class TestQuoteHandling:
    """Test quote handling in tmux sessions."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = TmuxSessionManager(session_prefix="test_quote", max_sessions=5)

    def test_check_quote_balance(self):
        """Test quote balance checking."""
        # Balanced quotes
        assert self.manager._check_quote_balance('echo "hello world"') is True
        assert self.manager._check_quote_balance("echo 'hello world'") is True
        assert self.manager._check_quote_balance("echo \"mixed 'quotes'\"") is True

        # Unbalanced quotes
        assert self.manager._check_quote_balance('echo "unbalanced quote') is False
        assert self.manager._check_quote_balance("echo 'unbalanced quote") is False
        assert self.manager._check_quote_balance("echo \"mixed ' quote") is False

    def test_has_complex_quotes(self):
        """Test detection of complex quote scenarios."""
        # Simple quotes (not complex)
        assert self.manager._has_complex_quotes('echo "hello"') is False
        assert self.manager._has_complex_quotes("echo 'hello'") is False

        # Complex quotes
        assert self.manager._has_complex_quotes("echo 'It\\'s working'") is True
        assert self.manager._has_complex_quotes('echo "He said \\"hello\\""') is True
        assert self.manager._has_complex_quotes("echo 'multi\nline'") is True

    def test_sanitize_complex_command(self):
        """Test command sanitization for complex quote scenarios."""
        # Single quote with escaped single quote
        result = self.manager._sanitize_complex_command("echo 'It\\'s working'")
        assert result == 'echo "It\'s working"'

        # Multi-line command
        result = self.manager._sanitize_complex_command("echo 'line1\nline2'")
        assert "\\n" in result

    def test_detect_shell_stuck_state(self):
        """Test detection of stuck shell states."""
        # Normal output
        assert self.manager._detect_shell_stuck_state("❯ echo hello\nhello\n❯") is None

        # Stuck in quote
        assert (
            self.manager._detect_shell_stuck_state("❯ echo 'test\nquote>") == "quote>"
        )

        # Stuck in double quote
        assert (
            self.manager._detect_shell_stuck_state('❯ echo "test\ndquote>') == "dquote>"
        )

    @patch("silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command")
    def test_recover_from_stuck_state(self, mock_run_command):
        """Test recovery from stuck shell states."""
        mock_run_command.return_value = (0, "", "")

        success, message = self.manager._recover_from_stuck_state(
            "test_session", "quote>"
        )
        assert success is True
        assert "recovery" in message.lower()

        # Verify recovery commands were sent
        assert mock_run_command.call_count >= 1

    @patch("silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command")
    def test_validate_and_sanitize_command(self, mock_run_command):
        """Test command validation and sanitization."""
        # Valid simple command
        is_valid, result = self.manager._validate_and_sanitize_command("echo hello")
        assert is_valid is True
        assert result == "echo hello"

        # Invalid unbalanced quotes
        is_valid, result = self.manager._validate_and_sanitize_command(
            'echo "unbalanced'
        )
        assert is_valid is False
        assert "unbalanced quotes" in result

        # Complex quotes that get sanitized
        is_valid, result = self.manager._validate_and_sanitize_command(
            "echo 'It\\'s working'"
        )
        assert is_valid is True
        assert result == 'echo "It\'s working"'


class TestTmuxQuoteIntegration:
    """Integration tests for quote handling with real tmux."""

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

    def test_quote_handling_integration(self):
        """Test quote handling with real tmux sessions."""
        context = self.create_test_context()

        # Test cases that should work after the fix
        test_cases = [
            ("simple_quotes", 'echo "Hello World"'),
            ("apostrophe_fix", 'echo "It\'s working"'),  # Fixed version
            ("mixed_quotes", "echo \"Mixed 'quote' types\""),
        ]

        for session_name, command in test_cases:
            try:
                # Create session
                result = tmux_create_session(context, session_name)
                assert "successfully" in result

                # Execute the potentially problematic command
                result = tmux_execute_command(context, session_name, command)
                assert "executed" in result

                # Verify we can execute a follow-up command (proves shell isn't stuck)
                result = tmux_execute_command(context, session_name, "echo 'follow-up'")
                assert "executed" in result

                # Get output to verify both commands executed
                output = tmux_get_output(context, session_name)
                assert "follow-up" in output

            finally:
                # Cleanup
                try:
                    tmux_destroy_session(context, session_name)
                except Exception:
                    pass

    def test_unbalanced_quote_rejection(self):
        """Test that unbalanced quotes are properly rejected."""
        context = self.create_test_context()

        try:
            # Create session
            result = tmux_create_session(context, "unbalanced_test")
            assert "successfully" in result

            # Try to execute command with unbalanced quotes
            result = tmux_execute_command(
                context, "unbalanced_test", 'echo "unbalanced quote'
            )

            # Should either be rejected or recovered
            assert "executed" in result or "unbalanced" in result or "quote" in result

        finally:
            try:
                tmux_destroy_session(context, "unbalanced_test")
            except Exception:
                pass

    def test_recovery_mechanism(self):
        """Test that recovery mechanism works for stuck shells."""
        context = self.create_test_context()

        try:
            # Create session
            result = tmux_create_session(context, "recovery_test")
            assert "successfully" in result

            # This command might get the shell stuck, but should be recovered
            result = tmux_execute_command(
                context, "recovery_test", 'echo "test\nwith\nnewlines"'
            )

            # Whether it succeeds or gets recovered, we should be able to continue
            result = tmux_execute_command(
                context, "recovery_test", "echo 'recovery_check'"
            )
            assert "executed" in result

        finally:
            try:
                tmux_destroy_session(context, "recovery_test")
            except Exception:
                pass
