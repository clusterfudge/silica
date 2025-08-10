"""Tests for the github_api tool function."""

from unittest.mock import patch, MagicMock
import pytest

from silica.developer.context import AgentContext
from silica.developer.tools.github import github_api


@pytest.fixture
def mock_context():
    """Create a mock agent context."""
    return MagicMock(spec=AgentContext)


@patch("silica.developer.tools.github._run_gh_command")
def test_github_api_with_dict_fields(mock_run_gh, mock_context):
    """Test github_api with dictionary fields parameter."""
    # Setup mock response
    mock_run_gh.return_value = {
        "success": True,
        "data": '{"status": "success", "data": {"id": 123, "name": "test"}}',
    }

    # Call with dictionary fields
    result = github_api(
        mock_context,
        endpoint="repos/owner/repo/issues",
        fields={"title": "Test Issue", "body": "Test Body"},
    )

    # Verify command construction
    args = mock_run_gh.call_args[0][0]
    assert "repos/owner/repo/issues" in args
    assert "--field" in args
    assert "title=Test Issue" in args[args.index("--field") + 1]
    assert (
        "body=Test Body" in args[args.index("--field", args.index("--field") + 1) + 1]
    )

    # Verify output formatting
    assert "GitHub API: repos/owner/repo/issues" in result
    assert "success" in result


@patch("silica.developer.tools.github._run_gh_command")
def test_github_api_with_string_fields(mock_run_gh, mock_context):
    """Test github_api with JSON string fields parameter."""
    # Setup mock response
    mock_run_gh.return_value = {
        "success": True,
        "data": '{"status": "success", "data": {"id": 123, "name": "test"}}',
    }

    # Call with string fields (JSON)
    result = github_api(
        mock_context,
        endpoint="repos/owner/repo/issues",
        fields='{"title": "Test Issue", "body": "Test Body"}',
    )

    # Verify command construction
    args = mock_run_gh.call_args[0][0]
    assert "repos/owner/repo/issues" in args
    assert "--field" in args
    assert "title=Test Issue" in args[args.index("--field") + 1]
    assert (
        "body=Test Body" in args[args.index("--field", args.index("--field") + 1) + 1]
    )

    # Verify output formatting
    assert "GitHub API: repos/owner/repo/issues" in result
    assert "success" in result


@patch("silica.developer.tools.github._run_gh_command")
def test_github_api_with_invalid_string_fields(mock_run_gh, mock_context):
    """Test github_api with invalid JSON string fields parameter."""
    # Call with invalid JSON string
    result = github_api(
        mock_context, endpoint="repos/owner/repo/issues", fields='{"title": "broken'
    )

    # Verify error is returned
    assert "Error: Unable to parse 'fields' as JSON" in result

    # Ensure _run_gh_command was not called
    mock_run_gh.assert_not_called()


@patch("silica.developer.tools.github._run_gh_command")
def test_github_api_with_non_dict_json(mock_run_gh, mock_context):
    """Test github_api with JSON string that doesn't represent a dict."""
    # Call with JSON array instead of object
    result = github_api(
        mock_context, endpoint="repos/owner/repo/issues", fields="[1, 2, 3]"
    )

    # Verify error is returned
    assert "Error: 'fields' must be a dictionary" in result

    # Ensure _run_gh_command was not called
    mock_run_gh.assert_not_called()


@patch("silica.developer.tools.github._run_gh_command")
def test_github_api_without_fields(mock_run_gh, mock_context):
    """Test github_api without fields parameter."""
    # Setup mock response
    mock_run_gh.return_value = {
        "success": True,
        "data": '{"status": "success"}',
    }

    # Call without fields
    result = github_api(mock_context, endpoint="repos/owner/repo")

    # Verify command construction
    args = mock_run_gh.call_args[0][0]
    assert "repos/owner/repo" in args
    assert "--field" not in args

    # Verify output formatting
    assert "GitHub API: repos/owner/repo" in result
    assert "success" in result
