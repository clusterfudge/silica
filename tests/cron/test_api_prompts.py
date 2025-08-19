"""Tests for prompts API endpoints."""

from unittest.mock import patch, MagicMock

from silica.cron.models import JobExecution


class TestPromptsAPI:
    """Test the prompts API endpoints."""

    def test_list_prompts_empty(self, client):
        """Test listing prompts when none exist."""
        response = client.get("/api/prompts/")

        assert response.status_code == 200
        assert response.json() == []

    def test_list_prompts_with_data(self, client, sample_prompt):
        """Test listing prompts with existing data."""
        response = client.get("/api/prompts/")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Prompt"
        assert data[0]["model"] == "haiku"
        assert data[0]["persona"] == "basic_agent"

    def test_create_prompt_minimal(self, client):
        """Test creating a prompt with minimal data."""
        prompt_data = {"name": "New Prompt", "prompt_text": "This is a new prompt"}

        response = client.post("/api/prompts/", json=prompt_data)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Prompt"
        assert data["prompt_text"] == "This is a new prompt"
        assert data["model"] == "haiku"  # Default
        assert data["persona"] == "basic_agent"  # Default
        assert data["description"] == ""  # Default
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_create_prompt_full(self, client):
        """Test creating a prompt with all fields."""
        prompt_data = {
            "name": "Full Prompt",
            "description": "A complete prompt with all fields",
            "prompt_text": "This is a comprehensive prompt",
            "model": "sonnet",
            "persona": "deep_research_agent",
        }

        response = client.post("/api/prompts/", json=prompt_data)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Full Prompt"
        assert data["description"] == "A complete prompt with all fields"
        assert data["prompt_text"] == "This is a comprehensive prompt"
        assert data["model"] == "sonnet"
        assert data["persona"] == "deep_research_agent"

    def test_create_prompt_invalid_model(self, client):
        """Test creating a prompt with invalid model."""
        prompt_data = {
            "name": "Invalid Model Prompt",
            "prompt_text": "Test prompt",
            "model": "invalid_model",
        }

        response = client.post("/api/prompts/", json=prompt_data)

        assert response.status_code == 422  # Validation error

    def test_create_prompt_invalid_persona(self, client):
        """Test creating a prompt with invalid persona."""
        prompt_data = {
            "name": "Invalid Persona Prompt",
            "prompt_text": "Test prompt",
            "persona": "invalid_persona",
        }

        response = client.post("/api/prompts/", json=prompt_data)

        assert response.status_code == 422  # Validation error

    def test_get_prompt_exists(self, client, sample_prompt):
        """Test getting an existing prompt."""
        response = client.get(f"/api/prompts/{sample_prompt.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_prompt.id
        assert data["name"] == sample_prompt.name
        assert data["prompt_text"] == sample_prompt.prompt_text

    def test_get_prompt_not_found(self, client):
        """Test getting a non-existent prompt."""
        response = client.get("/api/prompts/prompt_nonexistent999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_update_prompt(self, client, sample_prompt):
        """Test updating an existing prompt."""
        update_data = {
            "name": "Updated Prompt",
            "description": "Updated description",
            "prompt_text": "Updated prompt text",
            "model": "sonnet",
            "persona": "deep_research_agent",
        }

        response = client.put(f"/api/prompts/{sample_prompt.id}", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Prompt"
        assert data["description"] == "Updated description"
        assert data["prompt_text"] == "Updated prompt text"
        assert data["model"] == "sonnet"
        assert data["persona"] == "deep_research_agent"

    def test_update_prompt_not_found(self, client):
        """Test updating a non-existent prompt."""
        update_data = {"name": "Updated Prompt", "prompt_text": "Updated text"}

        response = client.put("/api/prompts/prompt_nonexistent999", json=update_data)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_delete_prompt(self, client, sample_prompt):
        """Test deleting an existing prompt."""
        response = client.delete(f"/api/prompts/{sample_prompt.id}")

        assert response.status_code == 200
        assert "deleted successfully" in response.json()["message"].lower()

        # Verify prompt was deleted
        get_response = client.get(f"/api/prompts/{sample_prompt.id}")
        assert get_response.status_code == 404

    def test_delete_prompt_not_found(self, client):
        """Test deleting a non-existent prompt."""
        response = client.delete("/api/prompts/prompt_nonexistent999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("silica.cron.routes.prompts.scheduler")
    def test_execute_prompt_manually(self, mock_scheduler, client, sample_prompt):
        """Test manually executing a prompt."""
        mock_scheduler._call_agent.return_value = ("Test response", "session-123")

        response = client.post(f"/api/prompts/{sample_prompt.id}/execute")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["execution_id"] is not None
        assert "execution started" in data["message"].lower()

    def test_execute_prompt_not_found(self, client):
        """Test executing a non-existent prompt."""
        response = client.post("/api/prompts/prompt_nonexistent999/execute")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("silica.cron.routes.prompts.scheduler")
    def test_execute_prompt_creates_execution_record(
        self, mock_scheduler, client, sample_prompt, db_session
    ):
        """Test that manual execution creates proper database records."""
        mock_scheduler._call_agent.return_value = ("Test response", "session-123")

        response = client.post(f"/api/prompts/{sample_prompt.id}/execute")
        execution_id = response.json()["execution_id"]

        # Check that execution record was created
        execution = (
            db_session.query(JobExecution)
            .filter(JobExecution.id == execution_id)
            .first()
        )
        assert execution is not None
        assert execution.scheduled_job_id is None  # Manual execution
        assert execution.status == "running"

    def test_get_execution_status(self, client, sample_prompt, sample_execution):
        """Test getting execution status."""
        response = client.get(
            f"/api/prompts/{sample_prompt.id}/executions/{sample_execution.id}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_execution.id
        assert data["status"] == sample_execution.status
        assert data["session_id"] == sample_execution.session_id
        assert data["output"] == sample_execution.output

    def test_get_execution_status_not_found(self, client, sample_prompt):
        """Test getting status for non-existent execution."""
        response = client.get(
            f"/api/prompts/{sample_prompt.id}/executions/exec_nonexistent123"
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestPromptExecutionBackgroundTask:
    """Test the background execution functionality."""

    @patch("silica.cron.routes.prompts.scheduler")
    @patch("silica.cron.routes.prompts.SessionLocal")
    def test_background_execution_success(
        self, mock_session_local, mock_scheduler, client, sample_prompt
    ):
        """Test successful background execution."""
        # Mock the background database session
        mock_bg_session = MagicMock()
        mock_session_local.return_value = mock_bg_session

        mock_execution = MagicMock()
        mock_execution.id = "exec_test123"
        mock_bg_session.query.return_value.filter.return_value.first.return_value = (
            mock_execution
        )

        # Mock scheduler success
        mock_scheduler._call_agent.return_value = ("Success response", "session-456")

        # Start execution
        response = client.post(f"/api/prompts/{sample_prompt.id}/execute")
        response.json()["execution_id"]

        # Give background thread time to complete
        import time

        time.sleep(0.1)

        assert response.status_code == 200

        # Verify scheduler was called with correct parameters
        mock_scheduler._call_agent.assert_called_once_with(
            prompt=sample_prompt.prompt_text,
            model=sample_prompt.model,
            persona=sample_prompt.persona,
        )

    @patch("silica.cron.routes.prompts.scheduler")
    @patch("silica.cron.routes.prompts.SessionLocal")
    def test_background_execution_failure(
        self, mock_session_local, mock_scheduler, client, sample_prompt
    ):
        """Test background execution with agent failure."""
        # Mock the background database session
        mock_bg_session = MagicMock()
        mock_session_local.return_value = mock_bg_session

        mock_execution = MagicMock()
        mock_execution.id = "exec_test456"
        mock_bg_session.query.return_value.filter.return_value.first.return_value = (
            mock_execution
        )

        # Mock scheduler failure
        mock_scheduler._call_agent.side_effect = Exception("Agent execution failed")

        # Start execution
        response = client.post(f"/api/prompts/{sample_prompt.id}/execute")

        # Give background thread time to complete
        import time

        time.sleep(0.1)

        assert response.status_code == 200  # Request succeeds even if execution fails

    @patch("threading.Thread")
    def test_background_thread_creation(self, mock_thread, client, sample_prompt):
        """Test that background thread is created for execution."""
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        response = client.post(f"/api/prompts/{sample_prompt.id}/execute")

        assert response.status_code == 200
        mock_thread.assert_called_once()
        mock_thread_instance.start.assert_called_once()
