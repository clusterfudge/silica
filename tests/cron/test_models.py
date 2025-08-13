"""Tests for cron models."""

import pytest
from datetime import datetime
from sqlalchemy.exc import IntegrityError

from silica.cron.models import Prompt, ScheduledJob, JobExecution


class TestPromptModel:
    """Test the Prompt model."""

    def test_create_prompt(self, db_session):
        """Test creating a prompt."""
        prompt = Prompt(
            name="Test Prompt",
            description="A test prompt",
            prompt_text="What is the weather today?",
            model="sonnet",
            persona="deep_research_agent",
        )

        db_session.add(prompt)
        db_session.commit()
        db_session.refresh(prompt)

        assert prompt.id is not None
        assert prompt.name == "Test Prompt"
        assert prompt.description == "A test prompt"
        assert prompt.prompt_text == "What is the weather today?"
        assert prompt.model == "sonnet"
        assert prompt.persona == "deep_research_agent"
        assert prompt.created_at is not None
        assert prompt.updated_at is not None

    def test_prompt_defaults(self, db_session):
        """Test prompt default values."""
        prompt = Prompt(name="Minimal Prompt", prompt_text="Hello")

        db_session.add(prompt)
        db_session.commit()
        db_session.refresh(prompt)

        assert prompt.model == "haiku"
        assert prompt.persona == "basic_agent"
        assert prompt.description is None

    def test_prompt_name_required(self, db_session):
        """Test that prompt name is required."""
        prompt = Prompt(prompt_text="Hello")
        db_session.add(prompt)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_prompt_text_required(self, db_session):
        """Test that prompt text is required."""
        prompt = Prompt(name="Test")
        db_session.add(prompt)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_prompt_relationship_with_jobs(self, db_session, sample_prompt):
        """Test prompt relationship with scheduled jobs."""
        job = ScheduledJob(
            name="Test Job", prompt_id=sample_prompt.id, cron_expression="0 * * * *"
        )
        db_session.add(job)
        db_session.commit()

        # Refresh to load relationships
        db_session.refresh(sample_prompt)

        assert len(sample_prompt.scheduled_jobs) == 1
        assert sample_prompt.scheduled_jobs[0].name == "Test Job"


class TestScheduledJobModel:
    """Test the ScheduledJob model."""

    def test_create_scheduled_job(self, db_session, sample_prompt):
        """Test creating a scheduled job."""
        job = ScheduledJob(
            name="Daily Report",
            prompt_id=sample_prompt.id,
            cron_expression="0 9 * * *",
            is_active=True,
        )

        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        assert job.id is not None
        assert job.name == "Daily Report"
        assert job.prompt_id == sample_prompt.id
        assert job.cron_expression == "0 9 * * *"
        assert job.is_active is True
        assert job.created_at is not None
        assert job.updated_at is not None

    def test_scheduled_job_defaults(self, db_session, sample_prompt):
        """Test scheduled job default values."""
        job = ScheduledJob(
            name="Test Job", prompt_id=sample_prompt.id, cron_expression="0 * * * *"
        )

        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        assert job.is_active is True

    def test_scheduled_job_required_fields(self, db_session, sample_prompt):
        """Test that required fields are enforced."""
        # Missing name
        job = ScheduledJob(prompt_id=sample_prompt.id, cron_expression="0 * * * *")
        db_session.add(job)

        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

        # Missing prompt_id
        job = ScheduledJob(name="Test", cron_expression="0 * * * *")
        db_session.add(job)

        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

        # Missing cron_expression
        job = ScheduledJob(name="Test", prompt_id=sample_prompt.id)
        db_session.add(job)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_scheduled_job_relationships(self, db_session, sample_job):
        """Test scheduled job relationships."""
        # Test prompt relationship
        assert sample_job.prompt is not None
        assert sample_job.prompt.name == "Test Prompt"

        # Create an execution
        execution = JobExecution(scheduled_job_id=sample_job.id, status="running")
        db_session.add(execution)
        db_session.commit()

        # Refresh to load relationships
        db_session.refresh(sample_job)

        assert len(sample_job.executions) == 1
        assert sample_job.executions[0].status == "running"


class TestJobExecutionModel:
    """Test the JobExecution model."""

    def test_create_job_execution(self, db_session, sample_job):
        """Test creating a job execution."""
        execution = JobExecution(
            scheduled_job_id=sample_job.id,
            session_id="test-session-456",
            status="running",
            output="Execution in progress",
        )

        db_session.add(execution)
        db_session.commit()
        db_session.refresh(execution)

        assert execution.id is not None
        assert execution.scheduled_job_id == sample_job.id
        assert execution.session_id == "test-session-456"
        assert execution.status == "running"
        assert execution.output == "Execution in progress"
        assert execution.started_at is not None
        assert execution.completed_at is None
        assert execution.error_message is None

    def test_job_execution_defaults(self, db_session):
        """Test job execution default values."""
        execution = JobExecution()

        db_session.add(execution)
        db_session.commit()
        db_session.refresh(execution)

        assert execution.status == "pending"
        assert execution.scheduled_job_id is None  # Allowed for manual executions
        assert execution.started_at is not None

    def test_manual_execution(self, db_session):
        """Test creating a manual execution (no scheduled job)."""
        execution = JobExecution(
            scheduled_job_id=None,  # Manual execution
            session_id="manual-session-123",
            status="completed",
            output="Manual execution result",
        )

        db_session.add(execution)
        db_session.commit()
        db_session.refresh(execution)

        assert execution.scheduled_job_id is None
        assert execution.session_id == "manual-session-123"
        assert execution.scheduled_job is None

    def test_execution_relationship(self, db_session, sample_execution):
        """Test job execution relationships."""
        assert sample_execution.scheduled_job is not None
        assert sample_execution.scheduled_job.name == "Test Job"

    def test_execution_status_update(self, db_session):
        """Test updating execution status and completion time."""
        execution = JobExecution(status="running")
        db_session.add(execution)
        db_session.commit()

        # Complete the execution
        execution.status = "completed"
        execution.completed_at = datetime.now()
        execution.output = "Task completed successfully"
        db_session.commit()

        db_session.refresh(execution)
        assert execution.status == "completed"
        assert execution.completed_at is not None
        assert execution.output == "Task completed successfully"

    def test_execution_with_error(self, db_session):
        """Test execution with error handling."""
        execution = JobExecution(
            status="failed",
            error_message="Something went wrong",
            completed_at=datetime.now(),
        )

        db_session.add(execution)
        db_session.commit()
        db_session.refresh(execution)

        assert execution.status == "failed"
        assert execution.error_message == "Something went wrong"
        assert execution.completed_at is not None
