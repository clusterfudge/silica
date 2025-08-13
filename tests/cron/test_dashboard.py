"""Tests for dashboard routes."""

import json
import tempfile
import os
from unittest.mock import patch
from pathlib import Path

from silica.cron.models import Prompt


class TestDashboardRoutes:
    """Test the HTML dashboard routes."""

    def test_root_dashboard(self, client):
        """Test the main dashboard page."""
        response = client.get("/")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        # Basic HTML structure checks
        content = response.text
        assert "<html>" in content or "<!DOCTYPE html>" in content
        assert "Dashboard" in content

    def test_prompts_page_empty(self, client):
        """Test the prompts page with no prompts."""
        response = client.get("/prompts")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        content = response.text
        assert "Prompts" in content or "prompts" in content

    def test_prompts_page_with_data(self, client, sample_prompt):
        """Test the prompts page with existing prompts."""
        response = client.get("/prompts")

        assert response.status_code == 200
        content = response.text
        assert sample_prompt.name in content
        assert sample_prompt.model in content
        assert sample_prompt.persona in content

    def test_jobs_page_empty(self, client):
        """Test the jobs page with no jobs."""
        response = client.get("/jobs")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        content = response.text
        assert "Jobs" in content or "jobs" in content or "Scheduled" in content

    def test_jobs_page_with_data(self, client, sample_job, sample_prompt):
        """Test the jobs page with existing jobs and prompts."""
        response = client.get("/jobs")

        assert response.status_code == 200
        content = response.text
        assert sample_job.name in content
        assert sample_job.cron_expression in content
        # Should also show available prompts for creating new jobs
        assert sample_prompt.name in content

    def test_create_prompt_form_valid(self, client):
        """Test creating a prompt via form submission."""
        form_data = {
            "name": "Form Created Prompt",
            "description": "Created via form",
            "prompt_text": "This prompt was created via HTML form",
            "model": "sonnet",
            "persona": "deep_research_agent",
        }

        response = client.post(
            "/prompts/create", data=form_data, follow_redirects=False
        )

        # Should redirect after creation
        assert response.status_code == 303
        assert response.headers["location"] == "/prompts"

        # Verify prompt was created
        list_response = client.get("/api/prompts/")
        prompts = list_response.json()
        assert len(prompts) == 1
        assert prompts[0]["name"] == "Form Created Prompt"
        assert prompts[0]["model"] == "sonnet"
        assert prompts[0]["persona"] == "deep_research_agent"

    def test_create_prompt_form_minimal(self, client):
        """Test creating a prompt via form with minimal data."""
        form_data = {"name": "Minimal Form Prompt", "prompt_text": "Minimal prompt"}

        response = client.post(
            "/prompts/create", data=form_data, follow_redirects=False
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/prompts"

        # Verify prompt was created with defaults
        list_response = client.get("/api/prompts/")
        prompts = list_response.json()
        assert len(prompts) == 1
        assert prompts[0]["name"] == "Minimal Form Prompt"
        assert prompts[0]["description"] == ""  # Default from form
        assert prompts[0]["model"] == "haiku"  # Default from form
        assert prompts[0]["persona"] == "basic_agent"  # Default from form

    def test_create_job_form_valid(self, client, sample_prompt):
        """Test creating a job via form submission."""
        form_data = {
            "name": "Form Created Job",
            "prompt_id": str(sample_prompt.id),
            "cron_expression": "0 10 * * *",
        }

        response = client.post("/jobs/create", data=form_data, follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/jobs"

        # Verify job was created
        list_response = client.get("/api/jobs/")
        jobs = list_response.json()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "Form Created Job"
        assert jobs[0]["prompt_id"] == sample_prompt.id
        assert jobs[0]["cron_expression"] == "0 10 * * *"

    def test_view_session_history_exists(self, client, temp_session_dir):
        """Test viewing session history for an existing session."""
        temp_dir, session_id, session_data = temp_session_dir

        response = client.get(f"/sessions/{session_id}")

        assert response.status_code == 200
        content = response.text
        assert session_id[:8] in content  # Truncated session ID should appear
        # Check that the session model information is displayed
        assert "Test Model" in content
        # Check that message content is displayed
        assert "Test prompt" in content
        assert "Test response" in content

    def test_view_session_history_not_found(self, client):
        """Test viewing session history for non-existent session."""
        response = client.get("/sessions/nonexistent-session-id")

        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    @patch("pathlib.Path.home")
    def test_view_session_history_invalid_json(self, mock_home, client):
        """Test viewing session history with invalid JSON file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_home.return_value = Path(temp_dir)

            # Create session directory with invalid JSON
            session_id = "invalid-json-session"
            session_dir = os.path.join(temp_dir, ".hdev", "history", session_id)
            os.makedirs(session_dir, exist_ok=True)

            session_file = os.path.join(session_dir, "root.json")
            with open(session_file, "w") as f:
                f.write("invalid json content")

            response = client.get(f"/sessions/{session_id}")

            assert response.status_code == 500
            assert "Invalid session file format" in response.json()["detail"]

    @patch("pathlib.Path.home")
    def test_view_session_history_file_error(self, mock_home, client):
        """Test viewing session history with file access error."""
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_home.return_value = Path(temp_dir)

            # Create session directory but make it unreadable
            session_id = "unreadable-session"
            session_dir = os.path.join(temp_dir, ".hdev", "history", session_id)
            os.makedirs(session_dir, exist_ok=True)

            session_file = os.path.join(session_dir, "root.json")
            with open(session_file, "w") as f:
                json.dump({"test": "data"}, f)

            # Mock file access error
            with patch("builtins.open", side_effect=PermissionError("Access denied")):
                response = client.get(f"/sessions/{session_id}")

                assert response.status_code == 500
                assert "Error loading session" in response.json()["detail"]


class TestDashboardTemplates:
    """Test dashboard template rendering and context."""

    def test_dashboard_template_context(self, client):
        """Test that dashboard template receives proper context."""
        response = client.get("/")

        assert response.status_code == 200
        # The template should render without errors
        content = response.text
        assert len(content) > 100  # Should have substantial content

        # Check for basic HTML structure
        assert "<html>" in content.lower() or "<!doctype html>" in content.lower()
        assert "<body>" in content.lower()
        assert "</body>" in content.lower()

    def test_prompts_template_context(self, client, sample_prompt):
        """Test that prompts template receives proper context with prompts."""
        response = client.get("/prompts")

        assert response.status_code == 200
        content = response.text

        # Should contain prompt information
        assert sample_prompt.name in content
        assert (
            sample_prompt.prompt_text in content or "..." in content
        )  # Might be truncated

        # Should have forms for creating new prompts
        assert "form" in content.lower()
        assert "name" in content.lower()
        assert "prompt_text" in content.lower() or "prompt-text" in content.lower()

    def test_jobs_template_context(self, client, sample_job, sample_prompt):
        """Test that jobs template receives proper context with jobs and prompts."""
        response = client.get("/jobs")

        assert response.status_code == 200
        content = response.text

        # Should contain job information
        assert sample_job.name in content
        assert sample_job.cron_expression in content

        # Should contain associated prompt information
        assert sample_prompt.name in content

        # Should have forms for creating new jobs
        assert "form" in content.lower()
        assert "cron" in content.lower()

    def test_session_history_template_context(self, client, temp_session_dir):
        """Test that session history template receives proper context."""
        temp_dir, session_id, session_data = temp_session_dir

        response = client.get(f"/sessions/{session_id}")

        assert response.status_code == 200
        content = response.text

        # Should contain session information
        assert session_id in content
        # The title field is not displayed in the template, so check for model instead
        assert session_data["model_spec"]["title"] in content

        # Should contain messages if they exist
        if "messages" in session_data:
            # Check that message content is rendered - messages have nested structure now
            assert "Test prompt" in content
            assert "Test response" in content
            # Note: The exact rendering depends on the template,
            # so we just check that the template renders successfully
            assert len(content) > 100  # Should have substantial content


class TestDashboardSecurity:
    """Test dashboard security and input validation."""

    def test_form_csrf_protection(self, client):
        """Test that forms include CSRF protection if implemented."""
        response = client.get("/prompts")

        assert response.status_code == 200
        # This test would need to be updated based on actual CSRF implementation
        # For now, just ensure the page loads
        assert "form" in response.text.lower()

    def test_xss_prevention_in_prompt_display(self, client, db_session):
        """Test that XSS attempts in prompts are properly escaped."""
        # Create a prompt with potential XSS content
        xss_prompt = Prompt(
            name="<script>alert('xss')</script>",
            description="<img src=x onerror=alert('xss')>",
            prompt_text="Normal prompt text",
            model="haiku",
            persona="basic_agent",
        )
        db_session.add(xss_prompt)
        db_session.commit()

        response = client.get("/prompts")

        assert response.status_code == 200
        content = response.text

        # Check that XSS content in prompt data is properly escaped
        # The malicious script tag in the name should be HTML-escaped
        assert "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" in content

        # The malicious img tag in description should be escaped
        assert "&lt;img src=x onerror=alert(&#39;xss&#39;)&gt;" in content

        # Ensure the malicious content is not executable (not in raw form where it could execute)
        # Look for the specific table cell content to avoid false positives from legitimate page scripts
        import re

        # Check that our malicious content appears in escaped form in table data
        table_content = re.search(r"<tbody>.*?</tbody>", content, re.DOTALL)
        if table_content:
            table_text = table_content.group(0)
            # The malicious content should only appear in escaped form in the table
            assert "<script>alert('xss')</script>" not in table_text
            assert "<img src=x onerror=alert('xss')>" not in table_text

    def test_session_id_validation(self, client):
        """Test that session ID parameter is properly validated."""
        # Test with potentially malicious session ID
        malicious_ids = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\system",
            "<script>alert('xss')</script>",
            "'; DROP TABLE sessions; --",
        ]

        for malicious_id in malicious_ids:
            response = client.get(f"/sessions/{malicious_id}")

            # Should either return 404 (not found) or 500 (error)
            # but not execute malicious content
            assert response.status_code in [404, 500]

            if response.status_code == 500:
                # Error message should not contain the malicious content
                detail = response.json().get("detail", "")
                assert "<script>" not in detail
                assert "DROP TABLE" not in detail
