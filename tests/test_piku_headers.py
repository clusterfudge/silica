"""Test piku header filtering functionality."""

import subprocess
from unittest.mock import patch
from pathlib import Path

import pytest

from silica.utils.piku import run_piku_in_silica


@pytest.fixture
def git_root_mock():
    with patch("silica.utils.piku.find_git_root") as mock_find_git_root:
        mock_find_git_root.return_value = Path("/mock/path")
        yield mock_find_git_root


@pytest.fixture
def run_in_silica_mock():
    with patch("silica.utils.piku.run_in_silica_dir") as mock_run:
        yield mock_run


def test_run_piku_with_capture_output_filters_headers(
    git_root_mock, run_in_silica_mock
):
    # Mock the result with Piku headers
    mock_result = subprocess.CompletedProcess(
        args=["mock_command"],
        returncode=0,
        stdout="Piku remote operator.\nServer: piku@test\nApp: test-app\nActual output line",
        stderr=None,
    )
    run_in_silica_mock.return_value = mock_result

    # Run the function with capture_output=True
    result = run_piku_in_silica(
        "status test-app",
        workspace_name="test",
        capture_output=True,
        filter_headers=True,
    )

    # Check that headers were filtered
    assert "Piku remote operator" not in result.stdout
    assert "Server: piku@test" not in result.stdout
    assert "App: test-app" not in result.stdout
    assert "Actual output line" in result.stdout


def test_run_piku_interactive_includes_header_filter(git_root_mock, run_in_silica_mock):
    # Call the function with capture_output=False (interactive mode)
    run_piku_in_silica(
        "status test-app",
        workspace_name="test",
        capture_output=False,
        filter_headers=True,
    )

    # Check that grep filter was added to the command
    expected_cmd = "piku -r test status test-app 2>&1 | grep -v -E '^(Piku remote operator\\.|Server: |App: )' || true"
    run_in_silica_mock.assert_called_with(
        expected_cmd, use_shell=True, capture_output=False, check=True
    )


def test_run_piku_interactive_no_filter_when_disabled(
    git_root_mock, run_in_silica_mock
):
    # Call the function with filter_headers=False
    run_piku_in_silica(
        "status test-app",
        workspace_name="test",
        capture_output=False,
        filter_headers=False,
    )

    # Check that grep filter was NOT added to the command
    expected_cmd = "piku -r test status test-app"
    run_in_silica_mock.assert_called_with(
        expected_cmd, use_shell=True, capture_output=False, check=True
    )


def test_run_piku_shell_pipe_with_header_filter(git_root_mock, run_in_silica_mock):
    # Call the function with use_shell_pipe=True
    run_piku_in_silica(
        "ls -la",
        workspace_name="test",
        use_shell_pipe=True,
        capture_output=False,
        filter_headers=True,
    )

    # Check that grep filter was added to the command
    expected_cmd = "echo \"ls -la && exit\" | piku -r test shell 2>&1 | grep -v -E '^(Piku remote operator\\.|Server: |App: )' || true"
    run_in_silica_mock.assert_called_with(
        expected_cmd, use_shell=True, capture_output=False, check=True
    )
