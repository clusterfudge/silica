"""Tests for jobs API endpoints."""

from silica.cron.models import JobExecution


class TestJobsAPI:
    """Test the scheduled jobs API endpoints."""

    def test_list_scheduled_jobs_empty(self, client):
        """Test listing scheduled jobs when none exist."""
        response = client.get("/api/jobs/")

        assert response.status_code == 200
        assert response.json() == []

    def test_list_scheduled_jobs_with_data(self, client, sample_job):
        """Test listing scheduled jobs with existing data."""
        response = client.get("/api/jobs/")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Job"
        assert data[0]["prompt_name"] == "Test Prompt"
        assert data[0]["cron_expression"] == "0 9 * * *"
        assert data[0]["is_active"] is True

    def test_create_scheduled_job_valid(self, client, sample_prompt):
        """Test creating a scheduled job with valid data."""
        job_data = {
            "name": "New Daily Job",
            "prompt_id": sample_prompt.id,
            "cron_expression": "0 8 * * *",
        }

        response = client.post("/api/jobs/", json=job_data)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Daily Job"
        assert data["prompt_id"] == sample_prompt.id
        assert data["prompt_name"] == sample_prompt.name
        assert data["cron_expression"] == "0 8 * * *"
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data

    def test_create_scheduled_job_invalid_cron(self, client, sample_prompt):
        """Test creating a scheduled job with invalid cron expression."""
        job_data = {
            "name": "Invalid Cron Job",
            "prompt_id": sample_prompt.id,
            "cron_expression": "invalid cron expression",
        }

        response = client.post("/api/jobs/", json=job_data)

        assert response.status_code == 400
        assert "Invalid cron expression" in response.json()["detail"]

    def test_create_scheduled_job_nonexistent_prompt(self, client):
        """Test creating a scheduled job with non-existent prompt."""
        job_data = {
            "name": "Job with Missing Prompt",
            "prompt_id": "prompt_nonexistent123",
            "cron_expression": "0 9 * * *",
        }

        response = client.post("/api/jobs/", json=job_data)

        assert response.status_code == 404
        assert "Prompt not found" in response.json()["detail"]

    def test_create_scheduled_job_various_cron_expressions(self, client, sample_prompt):
        """Test creating jobs with various valid cron expressions."""
        test_cases = [
            ("Every minute", "* * * * *"),
            ("Hourly", "0 * * * *"),
            ("Daily at midnight", "0 0 * * *"),
            ("Weekly on Monday", "0 9 * * 1"),
            ("Monthly on 1st", "0 9 1 * *"),
            ("Yearly on Jan 1st", "0 0 1 1 *"),
            ("Every 5 minutes", "*/5 * * * *"),
            ("Business hours", "0 9-17 * * 1-5"),
        ]

        for name, cron_expr in test_cases:
            job_data = {
                "name": name,
                "prompt_id": sample_prompt.id,
                "cron_expression": cron_expr,
            }

            response = client.post("/api/jobs/", json=job_data)
            assert response.status_code == 200, f"Failed for cron: {cron_expr}"
            assert response.json()["cron_expression"] == cron_expr

    def test_toggle_job_status_activate_to_deactivate(self, client, sample_job):
        """Test toggling job status from active to inactive."""
        # Job should start as active
        assert sample_job.is_active is True

        response = client.put(f"/api/jobs/{sample_job.id}/toggle")

        assert response.status_code == 200
        assert "deactivated" in response.json()["message"]

    def test_toggle_job_status_deactivate_to_activate(
        self, client, db_session, sample_job
    ):
        """Test toggling job status from inactive to active."""
        # First deactivate the job
        sample_job.is_active = False
        db_session.commit()

        response = client.put(f"/api/jobs/{sample_job.id}/toggle")

        assert response.status_code == 200
        assert "activated" in response.json()["message"]

    def test_toggle_job_status_not_found(self, client):
        """Test toggling status of non-existent job."""
        response = client.put("/api/jobs/job_nonexistent999/toggle")

        assert response.status_code == 404
        assert "Job not found" in response.json()["detail"]

    def test_delete_scheduled_job(self, client, sample_job):
        """Test deleting a scheduled job."""
        response = client.delete(f"/api/jobs/{sample_job.id}")

        assert response.status_code == 200
        assert "deleted successfully" in response.json()["message"].lower()

        # Verify job was deleted
        list_response = client.get("/api/jobs/")
        assert len(list_response.json()) == 0

    def test_delete_scheduled_job_not_found(self, client):
        """Test deleting a non-existent job."""
        response = client.delete("/api/jobs/job_nonexistent999")

        assert response.status_code == 404
        assert "Job not found" in response.json()["detail"]

    def test_get_job_executions_empty(self, client, sample_job):
        """Test getting executions for a job with no executions."""
        response = client.get(f"/api/jobs/{sample_job.id}/executions")

        assert response.status_code == 200
        assert response.json() == []

    def test_get_job_executions_with_data(self, client, sample_job, db_session):
        """Test getting executions for a job with execution history."""
        # Create multiple executions
        executions = []
        for i in range(3):
            execution = JobExecution(
                scheduled_job_id=sample_job.id,
                status=["pending", "running", "completed"][i],
                session_id=f"session-{i}",
                output=f"Output {i}",
            )
            db_session.add(execution)
            executions.append(execution)

        db_session.commit()

        response = client.get(f"/api/jobs/{sample_job.id}/executions")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

        # When executions have the same timestamp (created in same transaction),
        # they're returned in insertion order when ordered by started_at desc
        assert data[0]["status"] == "pending"
        assert data[1]["status"] == "running"
        assert data[2]["status"] == "completed"

    def test_get_job_executions_with_limit(self, client, sample_job, db_session):
        """Test getting executions with limit parameter."""
        # Create more executions than the limit
        for i in range(10):
            execution = JobExecution(
                scheduled_job_id=sample_job.id,
                status="completed",
                session_id=f"session-{i}",
            )
            db_session.add(execution)

        db_session.commit()

        response = client.get(f"/api/jobs/{sample_job.id}/executions?limit=5")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5

    def test_get_job_executions_fields(self, client, sample_execution):
        """Test that job executions return all expected fields."""
        job_id = sample_execution.scheduled_job_id
        response = client.get(f"/api/jobs/{job_id}/executions")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

        execution = data[0]
        assert "id" in execution
        assert "scheduled_job_id" in execution
        assert "session_id" in execution
        assert "started_at" in execution
        assert "completed_at" in execution
        assert "status" in execution
        assert "output" in execution
        assert "error_message" in execution

        assert execution["id"] == sample_execution.id
        assert execution["status"] == sample_execution.status
        assert execution["session_id"] == sample_execution.session_id
        assert execution["output"] == sample_execution.output


class TestJobsCronValidation:
    """Test cron expression validation in jobs API."""

    def test_valid_cron_expressions(self, client, sample_prompt):
        """Test various valid cron expressions."""
        valid_expressions = [
            "0 0 * * *",  # Daily at midnight
            "*/5 * * * *",  # Every 5 minutes
            "0 9 * * 1-5",  # Weekdays at 9 AM
            "0 0 1 * *",  # First day of month
            "0 0 1 1 *",  # January 1st yearly
            "15 10 * * *",  # Daily at 10:15
            "0 */2 * * *",  # Every 2 hours
            "30 1 * * 0",  # Sundays at 1:30 AM
            "* * * * * *",  # 6-field cron (with seconds) - croniter supports this
        ]

        for cron_expr in valid_expressions:
            job_data = {
                "name": f"Job for {cron_expr}",
                "prompt_id": sample_prompt.id,
                "cron_expression": cron_expr,
            }

            response = client.post("/api/jobs/", json=job_data)
            assert response.status_code == 200, f"Valid cron failed: {cron_expr}"

    def test_invalid_cron_expressions(self, client, sample_prompt):
        """Test various invalid cron expressions."""
        invalid_expressions = [
            "",  # Empty
            "* * * *",  # Too few fields
            "60 * * * *",  # Invalid minute
            "* 25 * * *",  # Invalid hour
            "* * 32 * *",  # Invalid day
            "* * * 13 *",  # Invalid month
            "* * * * 8",  # Invalid weekday
            "invalid",  # Not a number
            "a b c d e",  # Letters
            "*/0 * * * *",  # Division by zero
        ]

        for cron_expr in invalid_expressions:
            job_data = {
                "name": f"Invalid job for {cron_expr}",
                "prompt_id": sample_prompt.id,
                "cron_expression": cron_expr,
            }

            response = client.post("/api/jobs/", json=job_data)
            assert response.status_code == 400, f"Invalid cron accepted: {cron_expr}"
            assert "Invalid cron expression" in response.json()["detail"]


class TestJobsIntegration:
    """Integration tests for jobs functionality."""

    def test_create_job_and_list(self, client, sample_prompt):
        """Test creating a job and verifying it appears in list."""
        # Initially no jobs
        response = client.get("/api/jobs/")
        assert len(response.json()) == 0

        # Create a job
        job_data = {
            "name": "Integration Test Job",
            "prompt_id": sample_prompt.id,
            "cron_expression": "0 12 * * *",
        }

        create_response = client.post("/api/jobs/", json=job_data)
        assert create_response.status_code == 200
        job_id = create_response.json()["id"]

        # Verify it appears in list
        list_response = client.get("/api/jobs/")
        jobs = list_response.json()
        assert len(jobs) == 1
        assert jobs[0]["id"] == job_id
        assert jobs[0]["name"] == "Integration Test Job"

    def test_job_lifecycle(self, client, sample_prompt):
        """Test complete job lifecycle: create, toggle, delete."""
        # Create job
        job_data = {
            "name": "Lifecycle Test Job",
            "prompt_id": sample_prompt.id,
            "cron_expression": "0 6 * * *",
        }

        create_response = client.post("/api/jobs/", json=job_data)
        job_id = create_response.json()["id"]

        # Toggle to inactive
        toggle_response = client.put(f"/api/jobs/{job_id}/toggle")
        assert "deactivated" in toggle_response.json()["message"]

        # Toggle back to active
        toggle_response = client.put(f"/api/jobs/{job_id}/toggle")
        assert "activated" in toggle_response.json()["message"]

        # Delete job
        delete_response = client.delete(f"/api/jobs/{job_id}")
        assert delete_response.status_code == 200

        # Verify job is gone
        list_response = client.get("/api/jobs/")
        assert len(list_response.json()) == 0
