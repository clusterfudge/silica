"""Test direct piku implementation functionality."""

from unittest.mock import patch, MagicMock

import pytest

from silica.utils import piku_direct


@pytest.fixture
def mock_subprocess_run():
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "test-stdout"
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        yield mock_run


@pytest.fixture
def mock_os_execvp():
    with patch("os.execvp") as mock_execvp:
        mock_execvp.return_value = 0  # This won't actually be returned in real usage
        yield mock_execvp


@pytest.fixture
def mock_get_remote_info():
    with patch("silica.utils.piku_direct.get_remote_info") as mock_info:
        mock_info.return_value = ("piku@example.com", "test-app")
        yield mock_info


def test_get_remote_info():
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "piku@example.com:test-app\n"
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        server, app = piku_direct.get_remote_info("test-workspace")
        assert server == "piku@example.com"
        assert app == "test-app"
        mock_run.assert_called_with(
            "git config --get remote.test-workspace.url",
            shell=True,
            check=True,
            capture_output=True,
            text=True,
        )


def test_direct_ssh_command_interactive(mock_os_execvp):
    # Test interactive SSH command that replaces the current process
    piku_direct.direct_ssh_command("piku@example.com", "test-command", interactive=True)
    mock_os_execvp.assert_called_with(
        "ssh", ["ssh", "-t", "piku@example.com", "test-command"]
    )


def test_direct_ssh_command_non_interactive(mock_subprocess_run):
    # Test non-interactive SSH command
    result = piku_direct.direct_ssh_command(
        "piku@example.com", "test-command", interactive=False, capture_output=True
    )
    assert result.stdout == "test-stdout"
    mock_subprocess_run.assert_called_with(
        ["ssh", "piku@example.com", "test-command"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_shell_with_command(mock_get_remote_info, mock_subprocess_run):
    # Test running a single command in the shell
    result = piku_direct.shell("test-workspace", "ls -la", capture_output=True)
    assert result.stdout == "test-stdout"
    mock_subprocess_run.assert_called_with(
        ["ssh", "-t", "piku@example.com", "run test-app bash -c 'ls -la'"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_shell_interactive(mock_get_remote_info, mock_os_execvp):
    # Test interactive shell
    piku_direct.shell("test-workspace")
    mock_os_execvp.assert_called_with(
        "ssh", ["ssh", "-t", "piku@example.com", "run test-app bash"]
    )


def test_tmux_default(mock_get_remote_info, mock_os_execvp):
    # Test default tmux command (attach to session)
    piku_direct.tmux("test-workspace")
    mock_os_execvp.assert_called_with(
        "ssh",
        [
            "ssh",
            "-t",
            "piku@example.com",
            "run test-app tmux -- new-session -A -s test-app",
        ],
    )


def test_tmux_with_args(mock_get_remote_info, mock_os_execvp):
    # Test tmux with custom arguments
    piku_direct.tmux("test-workspace", ["ls"])
    mock_os_execvp.assert_called_with(
        "ssh", ["ssh", "-t", "piku@example.com", "run test-app tmux -- ls"]
    )


def test_agent_session(mock_get_remote_info, mock_os_execvp):
    # Test agent session
    piku_direct.agent_session("test-workspace")
    mock_os_execvp.assert_called_with(
        "ssh",
        [
            "ssh",
            "-t",
            "piku@example.com",
            "run test-app tmux -- new-session -A -s test-app './AGENT.sh; exec bash'",
        ],
    )


def test_run_command(mock_get_remote_info, mock_subprocess_run):
    # Test running a standard piku command
    result = piku_direct.run_command("status", "test-workspace", capture_output=True)
    assert result.stdout == "test-stdout"
    mock_subprocess_run.assert_called_with(
        ["ssh", "piku@example.com", "status test-app"],
        check=False,
        capture_output=True,
        text=True,
    )
