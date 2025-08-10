"""
Tests for SSH environment variable preservation in tmux sessions.
"""

import os
import unittest
from unittest.mock import patch
from silica.developer.tools.tmux_session import TmuxSessionManager


class TestTmuxSSHEnvPreservation(unittest.TestCase):
    """Test SSH environment variable preservation in tmux sessions."""

    def setUp(self):
        """Set up test environment."""
        self.session_manager = TmuxSessionManager(session_prefix="test_hdev")

    def tearDown(self):
        """Clean up after tests."""
        # Clean up any sessions created during tests
        try:
            self.session_manager.cleanup_all_sessions()
        except Exception:
            pass

    def test_get_environment_variables_for_tmux(self):
        """Test that environment variables are properly collected."""
        # Mock environment variables
        with patch.dict(
            os.environ,
            {
                "SSH_AUTH_SOCK": "/tmp/ssh-agent-123",
                "SSH_AGENT_PID": "1234",
                "DISPLAY": ":0",
                "TERM": "xterm-256color",
                "PATH": "/usr/bin:/bin",
            },
            clear=False,
        ):
            env_vars = self.session_manager._get_environment_variables_for_tmux()

            # Check that SSH variables are included
            self.assertEqual(env_vars["SSH_AUTH_SOCK"], "/tmp/ssh-agent-123")
            self.assertEqual(env_vars["SSH_AGENT_PID"], "1234")
            self.assertEqual(env_vars["DISPLAY"], ":0")
            self.assertEqual(env_vars["TERM"], "xterm-256color")
            self.assertEqual(env_vars["PATH"], "/usr/bin:/bin")

    def test_get_environment_variables_filters_none(self):
        """Test that None values are filtered out."""
        # Mock environment with some missing variables
        with patch.dict(
            os.environ, {"SSH_AUTH_SOCK": "/tmp/ssh-agent-123"}, clear=True
        ):
            env_vars = self.session_manager._get_environment_variables_for_tmux()

            # Should only include SSH_AUTH_SOCK, others should be filtered out
            self.assertIn("SSH_AUTH_SOCK", env_vars)
            self.assertEqual(env_vars["SSH_AUTH_SOCK"], "/tmp/ssh-agent-123")

            # These should not be present if not set in environment
            self.assertNotIn("SSH_AGENT_PID", env_vars)
            self.assertNotIn("SSH_CONNECTION", env_vars)

    @patch("silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command")
    def test_create_session_with_ssh_env(self, mock_run_tmux):
        """Test that SSH environment variables are passed when creating sessions."""
        # Mock successful tmux command
        mock_run_tmux.return_value = (0, "", "")

        # Mock environment variables
        with patch.dict(
            os.environ,
            {
                "SSH_AUTH_SOCK": "/tmp/ssh-agent-123",
                "SSH_AGENT_PID": "1234",
                "TERM": "xterm-256color",
            },
            clear=False,
        ):
            success, message = self.session_manager.create_session("test_session")

            self.assertTrue(success)
            self.assertIn("successfully", message)

            # Check that tmux command was called with environment variables
            mock_run_tmux.assert_called_once()
            call_args = mock_run_tmux.call_args[0][0]

            # Should contain tmux new-session command
            self.assertIn("tmux", call_args)
            self.assertIn("new-session", call_args)
            self.assertIn("-d", call_args)

            # Should contain environment variable arguments
            env_args = []
            for i, arg in enumerate(call_args):
                if arg == "-e" and i + 1 < len(call_args):
                    env_args.append(call_args[i + 1])

            # Check that SSH environment variables are included
            ssh_auth_found = any(
                "SSH_AUTH_SOCK=/tmp/ssh-agent-123" in arg for arg in env_args
            )
            ssh_pid_found = any("SSH_AGENT_PID=1234" in arg for arg in env_args)
            term_found = any("TERM=xterm-256color" in arg for arg in env_args)

            self.assertTrue(
                ssh_auth_found, f"SSH_AUTH_SOCK not found in env args: {env_args}"
            )
            self.assertTrue(
                ssh_pid_found, f"SSH_AGENT_PID not found in env args: {env_args}"
            )
            self.assertTrue(term_found, f"TERM not found in env args: {env_args}")

    @patch("silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command")
    def test_update_session_environment(self, mock_run_tmux):
        """Test updating environment variables for existing sessions."""
        # First create a session
        mock_run_tmux.return_value = (0, "", "")

        with patch.dict(
            os.environ, {"SSH_AUTH_SOCK": "/tmp/ssh-agent-123"}, clear=False
        ):
            success, message = self.session_manager.create_session("test_session")
            self.assertTrue(success)

            # Reset mock to test environment update
            mock_run_tmux.reset_mock()

            # Mock environment update with new SSH socket
            with patch.dict(
                os.environ, {"SSH_AUTH_SOCK": "/tmp/ssh-agent-456"}, clear=False
            ):
                success, message = self.session_manager.update_session_environment(
                    "test_session"
                )

                self.assertTrue(success)
                self.assertIn("Updated environment variables", message)

                # Check that setenv commands were called
                setenv_calls = [
                    call
                    for call in mock_run_tmux.call_args_list
                    if call[0][0] and "setenv" in call[0][0]
                ]

                self.assertGreater(len(setenv_calls), 0, "No setenv commands found")

                # Check that SSH_AUTH_SOCK was updated
                ssh_auth_updated = any(
                    "SSH_AUTH_SOCK" in call[0][0] and "/tmp/ssh-agent-456" in call[0][0]
                    for call in setenv_calls
                )
                self.assertTrue(ssh_auth_updated, "SSH_AUTH_SOCK was not updated")

    def test_update_session_environment_nonexistent_session(self):
        """Test updating environment for non-existent session."""
        success, message = self.session_manager.update_session_environment(
            "nonexistent"
        )

        self.assertFalse(success)
        self.assertIn("not found", message)

    @patch("silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command")
    def test_execute_command_with_env_refresh(self, mock_run_tmux):
        """Test executing command with environment refresh."""
        # Mock successful operations
        mock_run_tmux.return_value = (0, "", "")

        # Create session first
        with patch.dict(
            os.environ, {"SSH_AUTH_SOCK": "/tmp/ssh-agent-123"}, clear=False
        ):
            success, message = self.session_manager.create_session("test_session")
            self.assertTrue(success)

            # Reset mock and test command execution with env refresh
            mock_run_tmux.reset_mock()

            # Mock command execution methods
            with patch.object(
                self.session_manager, "_send_command_to_session_without_timeout"
            ) as mock_send_cmd:
                mock_send_cmd.return_value = (True, "Command sent")

                success, message = self.session_manager.execute_command(
                    "test_session", "echo hello", refresh_env=True
                )

                self.assertTrue(success)
                self.assertIn("env refreshed", message)

                # Should have called setenv commands for environment refresh
                setenv_calls = [
                    call
                    for call in mock_run_tmux.call_args_list
                    if call[0][0] and "setenv" in call[0][0]
                ]

                self.assertGreater(
                    len(setenv_calls), 0, "Environment was not refreshed"
                )


if __name__ == "__main__":
    unittest.main()
