"""Tests for structlog integration in antennae webapp."""

from unittest.mock import patch
from fastapi.testclient import TestClient

from silica.remote.antennae.webapp import app
from silica.remote.antennae.webapp import InitializeRequest, TellRequest


class TestAntennaeStructuredLogging:
    """Test structured logging functionality in antennae webapp."""

    def test_webapp_uses_structlog(self):
        """Test that webapp is configured to use structlog."""
        from silica.remote.antennae.webapp import logger

        # Verify we're using structlog
        assert hasattr(logger, "bind")  # structlog loggers have bind method
        assert hasattr(logger, "info")
        assert hasattr(logger, "error")

    def test_request_models_have_model_dump(self):
        """Test that request models use model_dump instead of deprecated dict()."""
        init_request = InitializeRequest(
            repo_url="https://github.com/test/repo.git", branch="feature-branch"
        )

        tell_request = TellRequest(message="test message")

        # Verify model_dump works
        init_data = init_request.model_dump()
        tell_data = tell_request.model_dump()

        assert init_data == {
            "repo_url": "https://github.com/test/repo.git",
            "branch": "feature-branch",
        }
        assert tell_data == {"message": "test message"}

    @patch("silica.remote.antennae.webapp.logger")
    @patch("silica.remote.antennae.webapp.agent_manager")
    @patch("silica.remote.antennae.webapp.config")
    def test_initialize_endpoint_logs_request_body(
        self, mock_config, mock_agent_manager, mock_logger
    ):
        """Test that initialize endpoint logs request body parameters."""
        # Setup mocks
        mock_config.get_workspace_name.return_value = "test-workspace"
        mock_agent_manager.clone_repository.return_value = True
        mock_agent_manager.setup_environment.return_value = True
        mock_agent_manager.start_tmux_session.return_value = True

        client = TestClient(app)

        # Make request
        response = client.post(
            "/initialize",
            json={"repo_url": "https://github.com/test/repo.git", "branch": "main"},
        )

        # Verify response is successful
        assert response.status_code == 200

        # Verify structured logging was called with request parameters
        mock_logger.info.assert_any_call(
            "initialize_workspace_started",
            workspace_name="test-workspace",
            repo_url="https://github.com/test/repo.git",
            branch="main",
            request_body={
                "repo_url": "https://github.com/test/repo.git",
                "branch": "main",
            },
        )

    @patch("silica.remote.antennae.webapp.logger")
    @patch("silica.remote.antennae.webapp.agent_manager")
    @patch("silica.remote.antennae.webapp.config")
    def test_tell_endpoint_logs_request_body(
        self, mock_config, mock_agent_manager, mock_logger
    ):
        """Test that tell endpoint logs request body parameters."""
        # Setup mocks
        mock_config.get_workspace_name.return_value = "test-workspace"
        mock_agent_manager.is_tmux_session_running.return_value = True
        mock_agent_manager.send_message_to_session.return_value = True

        client = TestClient(app)

        # Make request
        response = client.post(
            "/tell", json={"message": "Hello agent, please do something"}
        )

        # Verify response is successful
        assert response.status_code == 200

        # Verify structured logging was called with request parameters
        mock_logger.info.assert_any_call(
            "tell_agent_request",
            workspace_name="test-workspace",
            message_length=len("Hello agent, please do something"),
            request_body={"message": "Hello agent, please do something"},
        )

    @patch("silica.remote.antennae.webapp.logger")
    @patch("silica.remote.antennae.webapp.agent_manager")
    @patch("silica.remote.antennae.webapp.config")
    def test_structured_logging_on_errors(
        self, mock_config, mock_agent_manager, mock_logger
    ):
        """Test that errors are logged with structured logging."""
        # Setup mocks
        mock_config.get_workspace_name.return_value = "test-workspace"
        mock_agent_manager.clone_repository.side_effect = Exception("Test error")

        client = TestClient(app)

        # Make request that will fail
        response = client.post(
            "/initialize",
            json={"repo_url": "https://github.com/test/repo.git", "branch": "main"},
        )

        # Verify error response
        assert response.status_code == 500

        # Verify structured error logging was called
        mock_logger.error.assert_any_call(
            "initialize_workspace_unexpected_error",
            workspace_name="test-workspace",
            error="Test error",
            exc_info=True,
        )
