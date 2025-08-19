"""Tests for the main FastAPI application."""

from unittest.mock import patch

from silica.cron.app import app


class TestApp:
    """Test the main FastAPI application."""

    def test_health_endpoint(self, client):
        """Test the health check endpoint."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "cron"

    def test_root_endpoint(self, client):
        """Test the root endpoint returns dashboard."""
        response = client.get("/")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"

        # Should contain basic HTML structure
        content = response.text
        assert "<html>" in content.lower() or "<!doctype html>" in content.lower()
        assert "dashboard" in content.lower()

    def test_api_routes_included(self, client):
        """Test that API routes are properly included."""
        # Test prompts API
        response = client.get("/api/prompts/")
        assert response.status_code == 200

        # Test jobs API
        response = client.get("/api/jobs/")
        assert response.status_code == 200

    def test_dashboard_routes_included(self, client):
        """Test that dashboard routes are properly included."""
        # Test prompts dashboard
        response = client.get("/prompts")
        assert response.status_code == 200

        # Test jobs dashboard
        response = client.get("/jobs")
        assert response.status_code == 200

    def test_static_files_mounted(self, client):
        """Test that static files are properly mounted."""
        # This test assumes static files exist, or would return 404 if they don't
        response = client.get("/static/nonexistent.css")
        # Should return 404 for non-existent files, not 500
        assert response.status_code == 404

    def test_cors_headers(self, client):
        """Test CORS headers if configured."""
        response = client.get("/api/prompts/")

        # Basic check that response is valid
        assert response.status_code == 200

        # If CORS is configured, these headers might be present
        # This is a placeholder for actual CORS testing if needed
        headers = response.headers
        assert "content-type" in headers

    def test_openapi_docs_available(self, client):
        """Test that OpenAPI docs are available."""
        # FastAPI automatically provides docs at /docs
        response = client.get("/docs")
        assert response.status_code == 200

        # Should return HTML for the docs interface
        assert response.headers["content-type"].startswith("text/html")

    def test_openapi_json_available(self, client):
        """Test that OpenAPI JSON schema is available."""
        response = client.get("/openapi.json")
        assert response.status_code == 200

        # Should return JSON
        assert response.headers["content-type"] == "application/json"
        data = response.json()
        assert "openapi" in data
        assert "info" in data
        assert data["info"]["title"] == "cron"
        assert data["info"]["version"] == "0.1.0"

    @patch("silica.cron.app.scheduler")
    def test_lifespan_startup(self, mock_scheduler, client):
        """Test application lifespan startup."""
        # The lifespan should have started the scheduler
        # This is tested implicitly by creating the client
        # since the test client triggers the lifespan events

        # Make a request to ensure the app is running
        response = client.get("/health")
        assert response.status_code == 200

    def test_database_connection(self, client, test_db):
        """Test that database connection works."""
        # Create a prompt to test database operations
        prompt_data = {
            "name": "DB Test Prompt",
            "prompt_text": "Testing database connection",
        }

        response = client.post("/api/prompts/", json=prompt_data)
        assert response.status_code == 200

        # Verify we can read it back
        response = client.get("/api/prompts/")
        assert response.status_code == 200
        prompts = response.json()
        assert len(prompts) == 1
        assert prompts[0]["name"] == "DB Test Prompt"

    def test_error_handling_404(self, client):
        """Test 404 error handling."""
        response = client.get("/nonexistent-endpoint")
        assert response.status_code == 404

    def test_error_handling_method_not_allowed(self, client):
        """Test 405 method not allowed handling."""
        # Try POST on a GET-only endpoint
        response = client.post("/health")
        assert response.status_code == 405

    def test_json_validation_error(self, client):
        """Test JSON validation error handling."""
        # Send invalid JSON to create prompt endpoint
        response = client.post("/api/prompts/", json={"invalid": "data"})
        assert response.status_code == 422  # Validation error

    def test_content_type_handling(self, client):
        """Test that the app handles different content types."""
        # Test JSON API endpoint
        response = client.get("/api/prompts/")
        assert response.headers["content-type"] == "application/json"

        # Test HTML dashboard endpoint
        response = client.get("/")
        assert response.headers["content-type"] == "text/html; charset=utf-8"

        # Test health endpoint (JSON)
        response = client.get("/health")
        assert response.headers["content-type"] == "application/json"


class TestAppConfiguration:
    """Test application configuration and settings."""

    def test_app_title_and_description(self):
        """Test that app has correct title and description."""
        assert app.title == "cron"
        assert app.description == "Cron-style scheduling of agent prompts"
        assert app.version == "0.1.0"

    def test_router_tags(self, client):
        """Test that router tags are properly set."""
        # This is verified through the OpenAPI schema
        response = client.get("/openapi.json")
        assert response.status_code == 200

        openapi_data = response.json()

        # Check that tags are defined
        if "tags" in openapi_data:
            tag_names = [tag["name"] for tag in openapi_data["tags"]]
            expected_tags = ["prompts", "jobs", "dashboard"]
            for tag in expected_tags:
                assert tag in tag_names

    def test_dependency_overrides(self, test_db):
        """Test that dependency overrides work correctly."""
        # The test_db fixture should have already overridden get_db
        # This is tested implicitly by other tests that use the database

        from silica.cron.models import get_db

        assert get_db in app.dependency_overrides

    def test_database_table_creation(self, test_db):
        """Test that database tables are created on startup."""
        # The tables should be created when the test_db fixture sets up the database
        # We can verify this by checking that we can query without errors

        # Import here to ensure the models are available
        from silica.cron.models import Prompt

        # Try to create a session and query - if tables exist, this won't fail
        session = test_db()
        try:
            # This would fail if the table doesn't exist
            result = session.query(Prompt).first()
            # No exception means the table exists (even if empty)
            assert result is None  # Expected for empty test database
        finally:
            session.close()


class TestAppEntrypoint:
    """Test the application entrypoint function."""

    @patch("silica.cron.app.uvicorn.run")
    @patch("silica.cron.app.settings")
    def test_entrypoint_defaults(self, mock_settings, mock_run):
        """Test entrypoint with default parameters."""
        # Mock settings to return production defaults
        mock_settings.host = "127.0.0.1"
        mock_settings.port = 8080
        mock_settings.debug = False
        mock_settings.log_level = "info"

        from silica.cron.app import entrypoint

        entrypoint()

        mock_run.assert_called_once_with(
            app, host="127.0.0.1", port=8080, reload=False, log_level="info"
        )

    @patch("silica.cron.app.uvicorn.run")
    @patch("silica.cron.app.settings")
    def test_entrypoint_custom_params(self, mock_settings, mock_run):
        """Test entrypoint with custom parameters."""
        # Mock settings (won't be used since explicit params provided)
        mock_settings.host = "127.0.0.1"
        mock_settings.port = 8080
        mock_settings.debug = False
        mock_settings.log_level = "info"

        from silica.cron.app import entrypoint

        entrypoint(bind_host="0.0.0.0", bind_port=9000, debug=True, log_level="debug")

        mock_run.assert_called_once_with(
            "silica.cron.app:app",
            host="0.0.0.0",
            port=9000,
            reload=True,
            log_level="debug",
        )


class TestAppIntegration:
    """Integration tests for the complete application."""

    def test_full_workflow_api(self, client):
        """Test complete workflow through API endpoints."""
        # Create a prompt
        prompt_data = {
            "name": "Integration Test Prompt",
            "prompt_text": "This is an integration test",
            "model": "sonnet",
            "persona": "deep_research_agent",
        }

        response = client.post("/api/prompts/", json=prompt_data)
        assert response.status_code == 200
        prompt = response.json()
        prompt_id = prompt["id"]

        # Create a scheduled job
        job_data = {
            "name": "Integration Test Job",
            "prompt_id": prompt_id,
            "cron_expression": "0 9 * * *",
        }

        response = client.post("/api/jobs/", json=job_data)
        assert response.status_code == 200
        job = response.json()
        job_id = job["id"]

        # List jobs and verify
        response = client.get("/api/jobs/")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 1
        assert jobs[0]["id"] == job_id
        assert jobs[0]["prompt_name"] == "Integration Test Prompt"

        # Toggle job status
        response = client.put(f"/api/jobs/{job_id}/toggle")
        assert response.status_code == 200

        # Delete job
        response = client.delete(f"/api/jobs/{job_id}")
        assert response.status_code == 200

        # Delete prompt
        response = client.delete(f"/api/prompts/{prompt_id}")
        assert response.status_code == 200

        # Verify cleanup
        response = client.get("/api/prompts/")
        assert len(response.json()) == 0

        response = client.get("/api/jobs/")
        assert len(response.json()) == 0

    def test_full_workflow_dashboard(self, client):
        """Test complete workflow through dashboard forms."""
        # Create a prompt via form
        form_data = {
            "name": "Dashboard Test Prompt",
            "description": "Created via dashboard",
            "prompt_text": "Dashboard integration test",
            "model": "haiku",
            "persona": "basic_agent",
        }

        response = client.post(
            "/prompts/create", data=form_data, follow_redirects=False
        )
        assert response.status_code == 303

        # Verify prompt appears on dashboard
        response = client.get("/prompts")
        assert response.status_code == 200
        assert "Dashboard Test Prompt" in response.text

        # Get the prompt ID for job creation
        response = client.get("/api/prompts/")
        prompts = response.json()
        assert len(prompts) == 1
        prompt_id = prompts[0]["id"]

        # Create a job via form
        job_form_data = {
            "name": "Dashboard Test Job",
            "prompt_id": str(prompt_id),
            "cron_expression": "0 */6 * * *",
        }

        response = client.post(
            "/jobs/create", data=job_form_data, follow_redirects=False
        )
        assert response.status_code == 303

        # Verify job appears on dashboard
        response = client.get("/jobs")
        assert response.status_code == 200
        content = response.text
        assert "Dashboard Test Job" in content
        assert "0 */6 * * *" in content
