"""Test suite for antennae client retry logic, especially for 404 errors during piku app startup."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from silica.remote.utils.antennae_client import AntennaeClient, get_antennae_client


class TestAntennaeClientRetry:
    """Test retry logic in AntennaeClient."""

    @pytest.fixture
    def temp_silica_dir(self):
        """Create a temporary .silica directory structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            silica_dir = Path(temp_dir) / ".silica"
            silica_dir.mkdir(exist_ok=True)

            # Create minimal config
            config_file = silica_dir / "config.yaml"
            config_file.write_text("""
default_workspace: test-workspace
workspaces:
  test-workspace:
    piku_connection: "piku@test.example.com"
    app_name: "test-app"
    branch: "main"
    url: "http://test.example.com"
    is_local: false
""")

            yield silica_dir

    @pytest.fixture
    def antennae_client(self, temp_silica_dir):
        """Create an AntennaeClient for testing."""
        return AntennaeClient(temp_silica_dir, "test-workspace")

    def test_is_retryable_error_includes_404(self, antennae_client):
        """Test that 404 errors are considered retryable."""
        assert antennae_client._is_retryable_error(404) is True

    def test_is_retryable_error_includes_server_errors(self, antennae_client):
        """Test that server errors are still considered retryable."""
        assert antennae_client._is_retryable_error(500) is True
        assert antennae_client._is_retryable_error(502) is True
        assert antennae_client._is_retryable_error(503) is True
        assert antennae_client._is_retryable_error(504) is True

    def test_is_retryable_error_excludes_other_client_errors(self, antennae_client):
        """Test that other client errors are not considered retryable."""
        assert antennae_client._is_retryable_error(400) is False  # Bad Request
        assert antennae_client._is_retryable_error(401) is False  # Unauthorized
        assert antennae_client._is_retryable_error(403) is False  # Forbidden
        assert antennae_client._is_retryable_error(409) is False  # Conflict

    def test_is_retryable_error_excludes_success_codes(self, antennae_client):
        """Test that success codes are not considered retryable."""
        assert antennae_client._is_retryable_error(200) is False
        assert antennae_client._is_retryable_error(201) is False
        assert antennae_client._is_retryable_error(204) is False

    @patch("requests.get")
    def test_make_request_retries_on_404(self, mock_get, antennae_client):
        """Test that 404 errors trigger retry logic."""
        # First two attempts return 404, third succeeds
        mock_response_404 = Mock()
        mock_response_404.status_code = 404
        mock_response_404.json.return_value = {"error": "Not found"}
        mock_response_404.text = "Not found"

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {"status": "ok"}

        mock_get.side_effect = [
            mock_response_404,  # First attempt fails
            mock_response_404,  # Second attempt fails
            mock_response_success,  # Third attempt succeeds
        ]

        # Make request with retries
        success, response = antennae_client._make_request(
            "GET", "status", retries=2, retry_delay=0.1
        )

        # Should succeed on third attempt
        assert success is True
        assert response == {"status": "ok"}
        assert mock_get.call_count == 3

    @patch("requests.get")
    def test_make_request_retries_on_500(self, mock_get, antennae_client):
        """Test that 500 errors still trigger retry logic."""
        # First attempt returns 500, second succeeds
        mock_response_500 = Mock()
        mock_response_500.status_code = 500
        mock_response_500.json.return_value = {"error": "Internal server error"}
        mock_response_500.text = "Internal server error"

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {"status": "ok"}

        mock_get.side_effect = [
            mock_response_500,  # First attempt fails
            mock_response_success,  # Second attempt succeeds
        ]

        # Make request with retries
        success, response = antennae_client._make_request(
            "GET", "status", retries=1, retry_delay=0.1
        )

        # Should succeed on second attempt
        assert success is True
        assert response == {"status": "ok"}
        assert mock_get.call_count == 2

    @patch("requests.get")
    def test_make_request_no_retry_on_400(self, mock_get, antennae_client):
        """Test that 400 errors don't trigger retry logic."""
        mock_response_400 = Mock()
        mock_response_400.status_code = 400
        mock_response_400.json.return_value = {"error": "Bad request"}
        mock_response_400.text = "Bad request"

        mock_get.return_value = mock_response_400

        # Make request with retries
        success, response = antennae_client._make_request(
            "GET", "status", retries=3, retry_delay=0.1
        )

        # Should fail immediately without retries
        assert success is False
        assert "HTTP 400" in response["error"]
        assert mock_get.call_count == 1  # No retries

    @patch("requests.get")
    def test_make_request_exhausts_retries_on_persistent_404(
        self, mock_get, antennae_client
    ):
        """Test that persistent 404 errors eventually fail after exhausting retries."""
        mock_response_404 = Mock()
        mock_response_404.status_code = 404
        mock_response_404.json.return_value = {"error": "Not found"}
        mock_response_404.text = "Not found"

        mock_get.return_value = mock_response_404

        # Make request with limited retries
        success, response = antennae_client._make_request(
            "GET", "status", retries=2, retry_delay=0.1
        )

        # Should fail after exhausting retries
        assert success is False
        assert "HTTP 404" in response["error"]
        assert mock_get.call_count == 3  # Initial attempt + 2 retries

    @patch("time.sleep")
    @patch("requests.post")
    def test_initialize_uses_retries(self, mock_post, mock_sleep, antennae_client):
        """Test that initialize method uses retry logic correctly."""
        # First two attempts return 404 (app starting), third succeeds
        mock_response_404 = Mock()
        mock_response_404.status_code = 404
        mock_response_404.json.return_value = {"error": "Not found"}
        mock_response_404.text = "Not found"

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "success": True,
            "message": "Initialized",
        }

        mock_post.side_effect = [
            mock_response_404,  # First attempt fails
            mock_response_404,  # Second attempt fails
            mock_response_success,  # Third attempt succeeds
        ]

        # Test initialize with default retries=5
        success, response = antennae_client.initialize(
            "https://github.com/test/repo.git"
        )

        # Should succeed on third attempt
        assert success is True
        assert response == {"success": True, "message": "Initialized"}
        assert mock_post.call_count == 3

        # Verify correct data was sent
        call_args = mock_post.call_args_list[0]
        assert call_args[1]["json"] == {
            "repo_url": "https://github.com/test/repo.git",
            "branch": "main",
        }

    @patch("requests.get")
    def test_health_check_respects_timeout(self, mock_get, antennae_client):
        """Test that health_check uses proper timeout."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}

        mock_get.return_value = mock_response

        success, response = antennae_client.health_check()

        assert success is True
        # Verify timeout was set to 5.0 seconds
        call_args = mock_get.call_args
        assert call_args[1]["timeout"] == 5.0

    @patch("time.sleep")
    @patch("requests.get")
    def test_exponential_backoff_in_retries(
        self, mock_get, mock_sleep, antennae_client
    ):
        """Test that retry delays use exponential backoff."""
        mock_response_404 = Mock()
        mock_response_404.status_code = 404
        mock_response_404.json.return_value = {"error": "Not found"}
        mock_response_404.text = "Not found"

        mock_get.return_value = mock_response_404

        # Make request with retries
        success, response = antennae_client._make_request(
            "GET", "status", retries=3, retry_delay=1.0
        )

        # Should fail after all retries
        assert success is False

        # Verify exponential backoff: sleep(1.0), sleep(2.0), sleep(3.0)
        expected_sleeps = [1.0, 2.0, 3.0]
        actual_sleeps = [call.args[0] for call in mock_sleep.call_args_list]
        assert actual_sleeps == expected_sleeps

    def test_get_antennae_client_factory(self, temp_silica_dir):
        """Test that get_antennae_client factory function works correctly."""
        client = get_antennae_client(temp_silica_dir, "test-workspace", timeout=15.0)

        assert isinstance(client, AntennaeClient)
        assert client.workspace_name == "test-workspace"
        assert client.timeout == 15.0
        assert client.base_url == "http://test.example.com"


class TestPikuAppStartupScenario:
    """Integration-style tests simulating real piku app startup scenarios."""

    @pytest.fixture
    def temp_silica_dir(self):
        """Create a temporary .silica directory structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            silica_dir = Path(temp_dir) / ".silica"
            silica_dir.mkdir(exist_ok=True)

            # Create minimal config
            config_file = silica_dir / "config.yaml"
            config_file.write_text("""
default_workspace: test-workspace
workspaces:
  test-workspace:
    piku_connection: "piku@test.example.com"
    app_name: "test-app"
    branch: "main"
    url: "http://test.example.com"
    is_local: false
""")

            yield silica_dir

    @patch("time.sleep")
    @patch("requests.post")
    def test_piku_app_startup_simulation(self, mock_post, mock_sleep, temp_silica_dir):
        """Simulate a realistic piku app startup scenario."""
        client = get_antennae_client(temp_silica_dir, "test-workspace")

        # Simulate piku app startup sequence:
        # 1. First 3 requests: 404 (app not yet available)
        # 2. Fourth request: 200 (app now ready)

        responses = []

        # Create 404 responses (app starting up)
        for _ in range(3):
            response_404 = Mock()
            response_404.status_code = 404
            response_404.json.return_value = {"error": "Not found"}
            response_404.text = "Not found"
            responses.append(response_404)

        # Create success response (app ready)
        response_success = Mock()
        response_success.status_code = 200
        response_success.json.return_value = {
            "success": True,
            "message": "Repository initialized successfully",
        }
        responses.append(response_success)

        mock_post.side_effect = responses

        # Test initialize - should succeed after retries
        success, response = client.initialize(
            "https://github.com/example/project.git", branch="main"
        )

        # Verify success
        assert success is True
        assert response["success"] is True
        assert "initialized successfully" in response["message"]

        # Verify all attempts were made
        assert mock_post.call_count == 4

        # Verify request data was correct each time
        for call_args in mock_post.call_args_list:
            assert call_args[1]["json"] == {
                "repo_url": "https://github.com/example/project.git",
                "branch": "main",
            }

    @patch("time.sleep")
    @patch("requests.post")
    def test_piku_app_never_starts_scenario(
        self, mock_post, mock_sleep, temp_silica_dir
    ):
        """Simulate scenario where piku app never becomes available."""
        client = get_antennae_client(temp_silica_dir, "test-workspace")

        # App never becomes available - always returns 404
        response_404 = Mock()
        response_404.status_code = 404
        response_404.json.return_value = {"error": "Not found"}
        response_404.text = "Not found"

        mock_post.return_value = response_404

        # Test initialize with default retries (5)
        success, response = client.initialize("https://github.com/example/project.git")

        # Should fail after exhausting retries
        assert success is False
        assert "HTTP 404" in response["error"]

        # Should have made initial attempt + 5 retries = 6 total attempts
        assert mock_post.call_count == 6

    @patch("requests.get")
    def test_health_check_during_startup(self, mock_get, temp_silica_dir):
        """Test health check behavior during app startup."""
        client = get_antennae_client(temp_silica_dir, "test-workspace")

        # Simulate health check during startup - returns 404
        response_404 = Mock()
        response_404.status_code = 404
        response_404.json.return_value = {"error": "Not found"}
        response_404.text = "Not found"

        mock_get.return_value = response_404

        # Health check should fail (no retries by default)
        success, response = client.health_check()

        assert success is False
        assert "HTTP 404" in response["error"]

        # Should only make one attempt (health check doesn't use retries)
        assert mock_get.call_count == 1
