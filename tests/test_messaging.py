"""Tests for the messaging system."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from silica.utils.messaging import (
    check_messaging_app_exists,
    check_messaging_app_health,
    setup_workspace_messaging,
)


def test_check_messaging_app_exists():
    """Test checking if messaging app exists."""
    with patch("subprocess.run") as mock_run:
        # Test when app exists
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "app1\nsilica-messaging\napp2"

        result = check_messaging_app_exists("piku")
        assert result is True

        # Test when app doesn't exist
        mock_run.return_value.stdout = "app1\napp2"
        result = check_messaging_app_exists("piku")
        assert result is False

        # Test when command fails
        mock_run.return_value.returncode = 1
        result = check_messaging_app_exists("piku")
        assert result is False


def test_check_messaging_app_health():
    """Test messaging app health check."""
    with patch("silica.utils.messaging.requests.get") as mock_get:
        # Test healthy app
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = check_messaging_app_health()
        assert result is True

        # Test unhealthy app
        mock_response.status_code = 500
        result = check_messaging_app_health()
        assert result is False

        # Test connection error
        from requests import RequestException

        mock_get.side_effect = RequestException("Connection error")
        result = check_messaging_app_health()
        assert result is False


def test_setup_workspace_messaging():
    """Test workspace messaging setup."""
    with patch("silica.utils.piku.run_piku_in_silica") as mock_piku, patch(
        "requests.post"
    ) as mock_post, patch("time.sleep"):
        # Mock successful piku config
        mock_piku.return_value.returncode = 0

        # Mock successful thread creation
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"thread_id": "test-thread"}
        mock_post.return_value = mock_response

        success, message = setup_workspace_messaging("test", "project", "piku")

        assert success is True
        assert "completed" in message

        # Verify piku config was called
        mock_piku.assert_called()

        # Verify thread creation was attempted
        mock_post.assert_called_once()


@pytest.mark.integration
def test_messaging_function_availability():
    """Test that the silica-msg function is properly defined."""
    # Read the messaging.sh file
    messaging_file = Path(__file__).parent.parent / "silica" / "agent" / "messaging.sh"
    assert messaging_file.exists()

    content = messaging_file.read_text()

    # Check that silica-msg function is defined
    assert "silica-msg()" in content
    assert "export -f silica-msg" in content

    # Check that key functionality is present
    assert "SILICA_WORKSPACE" in content
    assert "SILICA_PROJECT" in content
    assert "curl" in content
    assert "/api/v1/messages/send" in content


@pytest.mark.integration
def test_messaging_command_availability():
    """Test that the messaging CLI command is properly implemented."""
    messaging_file = (
        Path(__file__).parent.parent / "silica" / "cli" / "commands" / "messaging.py"
    )
    assert messaging_file.exists()

    content = messaging_file.read_text()

    # Check that key endpoints are defined
    assert "/api/v1/agent/receive" in content
    assert "/health" in content
    assert "/api/v1/agent/status" in content

    # Check that Flask app is properly configured
    assert "from flask import Flask" in content
    assert "app = Flask(__name__)" in content

    # Check environment variable handling
    assert "SILICA_WORKSPACE" in content
    assert "SILICA_PROJECT" in content
    assert "SILICA_RECEIVER_PORT" in content
