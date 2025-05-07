"""Tests for piku utility functions."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from silica.utils.piku import run_in_silica_dir, run_piku_in_silica

# Mock test data
MOCK_CURRENT_DIR = Path("/path/to/current")
MOCK_GIT_ROOT = Path("/path/to/gitrepo")
MOCK_SILICA_DIR = MOCK_GIT_ROOT / ".silica"


@pytest.fixture
def mock_environment():
    """Set up mock environment for testing."""
    with patch("os.chdir") as mock_chdir, patch(
        "silica.utils.piku.find_git_root"
    ) as mock_find_git_root, patch(
        "silica.utils.piku.get_silica_dir"
    ) as mock_get_silica_dir, patch("pathlib.Path.cwd") as mock_cwd, patch(
        "pathlib.Path.exists"
    ) as mock_exists, patch("subprocess.run") as mock_run:
        # Set up mocks
        mock_cwd.return_value = MOCK_CURRENT_DIR
        mock_find_git_root.return_value = MOCK_GIT_ROOT
        mock_get_silica_dir.return_value = MOCK_SILICA_DIR
        mock_exists.return_value = True

        # Set up return value for subprocess.run
        mock_process = MagicMock()
        mock_process.stdout = "Command output"
        mock_run.return_value = mock_process

        yield {
            "chdir": mock_chdir,
            "find_git_root": mock_find_git_root,
            "get_silica_dir": mock_get_silica_dir,
            "cwd": mock_cwd,
            "exists": mock_exists,
            "run": mock_run,
            "process": mock_process,
        }


def test_run_in_silica_dir(mock_environment):
    """Test run_in_silica_dir function."""
    # Run the function
    result = run_in_silica_dir("test command")

    # Verify directory changes
    mock_environment["chdir"].assert_any_call(MOCK_SILICA_DIR)
    mock_environment["chdir"].assert_any_call(MOCK_CURRENT_DIR)

    # Verify command was run
    mock_environment["run"].assert_called_once_with(
        "test command", shell=True, capture_output=False, check=True, text=True
    )

    assert result == mock_environment["process"]


def test_run_piku_in_silica_direct(mock_environment):
    """Test run_piku_in_silica with direct command."""
    # Run the function with required workspace_name
    run_piku_in_silica("status", workspace_name="agent")

    # Verify command formatting with workspace name
    mock_environment["run"].assert_called_once_with(
        "piku -r agent status",
        shell=True,
        capture_output=False,
        check=True,
        text=True,
    )


def test_run_piku_in_silica_with_explicit_remote(mock_environment):
    """Test run_piku_in_silica with explicit remote."""
    # Run the function with explicit workspace name
    run_piku_in_silica("status", workspace_name="custom-remote")

    # Verify command formatting with workspace name
    mock_environment["run"].assert_called_once_with(
        "piku -r custom-remote status",
        shell=True,
        capture_output=False,
        check=True,
        text=True,
    )


def test_run_piku_in_silica_shell_pipe(mock_environment):
    """Test run_piku_in_silica with shell pipe."""
    # Run the function with required workspace_name
    run_piku_in_silica("status", workspace_name="agent", use_shell_pipe=True)

    # Verify command formatting with pipe
    mock_environment["run"].assert_called_once_with(
        'echo "status && exit" | piku -r agent shell',
        shell=True,
        capture_output=False,
        check=True,
        text=True,
    )


def test_error_handling_no_git_repo(mock_environment):
    """Test error handling when not in a git repository."""
    # Set up mock to simulate not being in a git repository
    mock_environment["find_git_root"].return_value = None

    # Run the function and check for ValueError
    with pytest.raises(ValueError, match="Not in a git repository"):
        run_in_silica_dir("test command")


def test_error_handling_no_silica_dir(mock_environment):
    """Test error handling when no .silica directory exists."""
    # Set up mock to simulate missing .silica directory
    mock_environment["exists"].return_value = False

    # Run the function and check for ValueError
    with pytest.raises(ValueError, match="No .silica directory found"):
        run_in_silica_dir("test command")
