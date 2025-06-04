"""Test for silica tell command functionality."""

import pytest
from unittest.mock import patch, MagicMock
from silica.cli.commands.tell import tell
from click.testing import CliRunner


def test_tell_command_invokes_correct_piku_and_tmux():
    """Test that tell command constructs the correct piku command with tmux send-keys."""
    runner = CliRunner()

    with patch("silica.cli.commands.tell.find_git_root") as mock_git_root, patch(
        "silica.cli.commands.tell.piku_utils.get_app_name"
    ) as mock_get_app_name, patch(
        "silica.cli.commands.tell.piku_utils.get_piku_connection_for_workspace"
    ) as mock_get_connection, patch(
        "silica.cli.commands.tell.piku_utils.run_piku_in_silica"
    ) as mock_run_piku:
        # Setup mocks
        mock_git_root.return_value = "/fake/git/root"
        mock_get_app_name.return_value = "test-app-name"
        mock_get_connection.return_value = "piku"
        mock_run_piku.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Run the command
        result = runner.invoke(tell, ["hello", "world", "-w", "test-workspace"])

        # Verify git root was called
        mock_git_root.assert_called_once()

        # Verify app name was constructed correctly
        mock_get_app_name.assert_called_once_with(
            "/fake/git/root", workspace_name="test-workspace"
        )

        # Verify piku connection was retrieved correctly
        mock_get_connection.assert_called_once_with("test-workspace", "/fake/git/root")

        # Verify the piku command was called with correct parameters
        mock_run_piku.assert_called_once()

        # Get the actual command that was passed to run_piku_in_silica
        call_args = mock_run_piku.call_args
        command_arg = call_args[0][0]  # First positional argument
        connection_arg = call_args[0][1]  # Second positional argument (piku connection)
        capture_output_kwarg = call_args[1][
            "capture_output"
        ]  # capture_output keyword arg

        # Verify the command structure
        assert "run --" in command_arg
        assert "tmux send-keys -t test-app-name" in command_arg
        assert "'hello world'" in command_arg
        assert "C-m" in command_arg
        assert connection_arg == "piku"
        assert capture_output_kwarg is True

        # Command should be successful
        assert result.exit_code == 0


def test_tell_command_handles_piku_failure():
    """Test that tell command handles piku command failures gracefully."""
    runner = CliRunner()

    with patch("silica.cli.commands.tell.find_git_root") as mock_git_root, patch(
        "silica.cli.commands.tell.piku_utils.get_app_name"
    ) as mock_get_app_name, patch(
        "silica.cli.commands.tell.piku_utils.get_piku_connection_for_workspace"
    ) as mock_get_connection, patch(
        "silica.cli.commands.tell.piku_utils.run_piku_in_silica"
    ) as mock_run_piku:
        # Setup mocks
        mock_git_root.return_value = "/fake/git/root"
        mock_get_app_name.return_value = "test-app-name"
        mock_get_connection.return_value = "piku"
        mock_run_piku.return_value = MagicMock(
            returncode=1, stdout="piku stdout", stderr="piku stderr"
        )

        # Run the command
        result = runner.invoke(tell, ["hello", "-w", "test-workspace"])

        # Verify the command completes even with piku failure
        assert result.exit_code == 0

        # Verify error message is displayed
        assert "Error sending message" in result.output


def test_tell_command_handles_missing_git_root():
    """Test that tell command handles missing git root gracefully."""
    runner = CliRunner()

    with patch("silica.cli.commands.tell.find_git_root") as mock_git_root:
        mock_git_root.return_value = None

        # Run the command
        result = runner.invoke(tell, ["hello"])

        # Should complete and show error message
        assert result.exit_code == 0
        assert "Not in a git repository" in result.output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
