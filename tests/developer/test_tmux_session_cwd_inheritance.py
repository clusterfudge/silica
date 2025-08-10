"""
Test that tmux sessions inherit the current working directory from the parent process.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from silica.developer.tools.tmux_session import TmuxSessionManager


class TestTmuxSessionCwdInheritance(unittest.TestCase):
    """Test cases for tmux session working directory inheritance."""

    def setUp(self):
        """Set up test fixtures."""
        self.session_manager = TmuxSessionManager()

    @patch("silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command")
    def test_create_session_inherits_cwd(self, mock_run_tmux):
        """Test that create_session uses current working directory."""
        # Mock successful tmux command
        mock_run_tmux.return_value = (0, "", "")

        # Create a temporary directory to test with
        with tempfile.TemporaryDirectory() as temp_dir:
            # Change to the temporary directory
            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)

                # Create a session
                success, message = self.session_manager.create_session("test_session")

                # Verify success
                self.assertTrue(success)

                # Verify that tmux was called with the correct working directory
                mock_run_tmux.assert_called_once()
                args, kwargs = mock_run_tmux.call_args
                command = args[0]

                # Check that the command includes -c with the current directory
                self.assertIn("tmux", command)
                self.assertIn("new-session", command)
                self.assertIn("-c", command)

                # Find the position of -c and check the next argument is our temp directory
                c_index = command.index("-c")
                actual_cwd = command[c_index + 1]
                # On macOS, os.getcwd() may return /private/var/... while tempfile returns /var/...
                # Use os.path.realpath to normalize both paths for comparison
                self.assertEqual(
                    os.path.realpath(actual_cwd), os.path.realpath(temp_dir)
                )

            finally:
                # Restore original working directory
                os.chdir(original_cwd)

    @patch("silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command")
    def test_create_session_with_initial_command_inherits_cwd(self, mock_run_tmux):
        """Test that create_session with initial command uses current working directory."""
        # Mock successful tmux command for session creation
        mock_run_tmux.return_value = (0, "", "")

        # Mock the _send_command_to_session method to avoid sending actual commands
        with patch.object(
            self.session_manager, "_send_command_to_session"
        ) as mock_send:
            mock_send.return_value = (True, "Command sent")

            # Create a temporary directory to test with
            with tempfile.TemporaryDirectory() as temp_dir:
                # Change to the temporary directory
                original_cwd = os.getcwd()
                try:
                    os.chdir(temp_dir)

                    # Create a session with initial command
                    success, message = self.session_manager.create_session(
                        "test_session", "echo hello"
                    )

                    # Verify success
                    self.assertTrue(success)

                    # Verify that tmux was called with the correct working directory
                    mock_run_tmux.assert_called_once()
                    args, kwargs = mock_run_tmux.call_args
                    command = args[0]

                    # Check that the command includes -c with the current directory
                    self.assertIn("-c", command)
                    c_index = command.index("-c")
                    actual_cwd = command[c_index + 1]
                    # On macOS, os.getcwd() may return /private/var/... while tempfile returns /var/...
                    # Use os.path.realpath to normalize both paths for comparison
                    self.assertEqual(
                        os.path.realpath(actual_cwd), os.path.realpath(temp_dir)
                    )

                    # Verify that initial command was sent separately
                    mock_send.assert_called_once()

                finally:
                    # Restore original working directory
                    os.chdir(original_cwd)

    def test_multiple_directories(self):
        """Test that different working directories result in different session cwds."""
        with patch(
            "silica.developer.tools.tmux_session.TmuxSessionManager._run_tmux_command"
        ) as mock_run_tmux:
            mock_run_tmux.return_value = (0, "", "")

            with tempfile.TemporaryDirectory() as temp_dir1:
                with tempfile.TemporaryDirectory() as temp_dir2:
                    original_cwd = os.getcwd()

                    try:
                        # Test first directory
                        os.chdir(temp_dir1)
                        self.session_manager.create_session("session1")

                        # Get the first call
                        first_call = mock_run_tmux.call_args_list[0]
                        first_command = first_call[0][0]
                        first_c_index = first_command.index("-c")
                        first_cwd = first_command[first_c_index + 1]

                        # Test second directory
                        os.chdir(temp_dir2)

                        # Reset the session manager to avoid session name conflicts
                        self.session_manager.sessions.clear()

                        self.session_manager.create_session("session2")

                        # Get the second call
                        second_call = mock_run_tmux.call_args_list[1]
                        second_command = second_call[0][0]
                        second_c_index = second_command.index("-c")
                        second_cwd = second_command[second_c_index + 1]

                        # Verify different directories were used (normalize paths for comparison)
                        self.assertEqual(
                            os.path.realpath(first_cwd), os.path.realpath(temp_dir1)
                        )
                        self.assertEqual(
                            os.path.realpath(second_cwd), os.path.realpath(temp_dir2)
                        )
                        self.assertNotEqual(
                            os.path.realpath(first_cwd), os.path.realpath(second_cwd)
                        )

                    finally:
                        os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
