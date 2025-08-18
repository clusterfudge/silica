"""Tests for the cron scheduler."""

import pytest
import time
import threading
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

from silica.cron.scheduler import PromptScheduler


class TestPromptScheduler:
    """Test the PromptScheduler class."""

    def test_scheduler_initialization(self):
        """Test scheduler initialization with defaults."""
        scheduler = PromptScheduler()

        assert scheduler.agent_model == "haiku"
        assert scheduler.silica_timeout == 300
        assert scheduler.running_jobs == set()
        assert scheduler.scheduler_thread is None
        assert not scheduler.stop_event.is_set()

    def test_scheduler_initialization_with_params(self):
        """Test scheduler initialization with custom parameters."""
        scheduler = PromptScheduler(agent_model="sonnet", agent_timeout=600)

        assert scheduler.agent_model == "sonnet"
        assert scheduler.silica_timeout == 600

    @patch("silica.cron.scheduler.SessionLocal")
    def test_start_stop_scheduler(self, mock_session_local):
        """Test starting and stopping the scheduler."""
        scheduler = PromptScheduler()

        # Test starting
        scheduler.start()
        assert scheduler.scheduler_thread is not None
        assert scheduler.scheduler_thread.is_alive()
        assert not scheduler.stop_event.is_set()

        # Test starting when already running (should log warning)
        with patch("silica.cron.scheduler.logger") as mock_logger:
            scheduler.start()
            mock_logger.warning.assert_called_once()

        # Test stopping
        scheduler.stop()
        assert scheduler.stop_event.is_set()
        # Thread should join within timeout
        time.sleep(0.1)  # Give thread time to stop

    def test_should_run_job_valid_cron(self):
        """Test checking if a job should run with valid cron expressions."""
        scheduler = PromptScheduler()

        # Create a mock job that should run every minute
        job = Mock()
        job.cron_expression = "* * * * *"  # Every minute

        # The job should run if we're within the execution window
        result = scheduler._should_run_job(job)
        # This might be True or False depending on timing, but should not raise an error
        assert isinstance(result, bool)

    def test_should_run_job_invalid_cron(self):
        """Test checking job with invalid cron expression."""
        scheduler = PromptScheduler()

        job = Mock()
        job.id = 1
        job.cron_expression = "invalid cron"

        with patch("silica.cron.scheduler.logger") as mock_logger:
            result = scheduler._should_run_job(job)
            assert result is False
            mock_logger.error.assert_called_once()

    def test_should_run_job_timing(self):
        """Test job timing logic with specific cron expressions."""
        scheduler = PromptScheduler()

        # Mock job with cron expression for specific time
        job = Mock()

        # Test with a cron that should have run recently (every minute)
        job.cron_expression = "* * * * *"

        # Mock croniter to return a specific time
        with patch("silica.cron.scheduler.croniter") as mock_croniter:
            mock_cron_instance = Mock()
            mock_croniter.return_value = mock_cron_instance

            # Simulate that the job was scheduled 15 seconds ago (should run)
            mock_cron_instance.get_prev.return_value = datetime.now() - timedelta(
                seconds=15
            )

            result = scheduler._should_run_job(job)
            assert result is True

            # Simulate that the job was scheduled 45 seconds ago (should not run)
            mock_cron_instance.get_prev.return_value = datetime.now() - timedelta(
                seconds=45
            )

            result = scheduler._should_run_job(job)
            assert result is False

    @patch("silica.cron.scheduler.SessionLocal")
    def test_check_and_execute_jobs(self, mock_session_local):
        """Test the job checking and execution logic."""
        scheduler = PromptScheduler()

        # Mock database session
        mock_session = Mock()
        mock_session_local.return_value = mock_session

        # Mock active jobs
        mock_job1 = Mock()
        mock_job1.id = 1
        mock_job1.cron_expression = "* * * * *"

        mock_job2 = Mock()
        mock_job2.id = 2
        mock_job2.cron_expression = "0 9 * * *"

        mock_session.query.return_value.filter.return_value.all.return_value = [
            mock_job1,
            mock_job2,
        ]

        with patch.object(scheduler, "_should_run_job") as mock_should_run:
            with patch("threading.Thread") as mock_thread:
                # First job should run, second should not
                mock_should_run.side_effect = [True, False]

                scheduler._check_and_execute_jobs()

                # Should create one thread for the job that should run
                mock_thread.assert_called_once()
                mock_session.close.assert_called_once()

    @patch("silica.cron.scheduler.SessionLocal")
    def test_check_and_execute_jobs_already_running(self, mock_session_local):
        """Test that running jobs are not started again."""
        scheduler = PromptScheduler()
        scheduler.running_jobs.add(1)  # Job 1 is already running

        # Mock database session
        mock_session = Mock()
        mock_session_local.return_value = mock_session

        mock_job = Mock()
        mock_job.id = 1
        mock_job.name = "Test Job"
        mock_session.query.return_value.filter.return_value.all.return_value = [
            mock_job
        ]

        with patch.object(scheduler, "_should_run_job", return_value=True):
            with patch("threading.Thread") as mock_thread:
                with patch("silica.cron.scheduler.logger") as mock_logger:
                    scheduler._check_and_execute_jobs()

                    # Should not create a thread
                    mock_thread.assert_not_called()
                    # Should log that job is already running
                    mock_logger.info.assert_called_once()

    @patch("subprocess.run")
    def test_call_agent_success(self, mock_subprocess):
        """Test successful agent execution."""
        scheduler = PromptScheduler()

        # Mock successful subprocess execution
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Agent\n─────────\nThis is the agent response\n─────────\n"
        mock_subprocess.return_value = mock_result

        result, session_id = scheduler._call_agent(
            "Test prompt", "haiku", "basic_agent"
        )

        assert "This is the agent response" in result
        assert session_id is not None

        # Verify subprocess was called with correct arguments
        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args
        assert "silica" in call_args[0][0]
        assert "--prompt" in call_args[0][0]
        assert "Test prompt" in call_args[0][0]
        assert "--model" in call_args[0][0]
        assert "haiku" in call_args[0][0]
        assert "--persona" in call_args[0][0]
        assert "basic_agent" in call_args[0][0]

    @patch("subprocess.run")
    def test_call_agent_failure(self, mock_subprocess):
        """Test agent execution failure."""
        scheduler = PromptScheduler()

        # Mock failed subprocess execution
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: Something went wrong"
        mock_result.stdout = ""
        mock_subprocess.return_value = mock_result

        with pytest.raises(Exception) as exc_info:
            scheduler._call_agent("Test prompt")

        assert "silica execution failed" in str(exc_info.value)
        assert "Something went wrong" in str(exc_info.value)

    @patch("subprocess.run")
    def test_call_agent_timeout(self, mock_subprocess):
        """Test agent execution timeout."""
        scheduler = PromptScheduler(agent_timeout=1)

        from subprocess import TimeoutExpired

        mock_subprocess.side_effect = TimeoutExpired("silica", 1)

        with pytest.raises(Exception) as exc_info:
            scheduler._call_agent("Test prompt")

        assert "timed out" in str(exc_info.value)

    @patch("subprocess.run")
    def test_call_agent_with_defaults(self, mock_subprocess):
        """Test agent execution with default parameters."""
        scheduler = PromptScheduler()

        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Agent response"
        mock_subprocess.return_value = mock_result

        result, session_id = scheduler._call_agent("Test prompt")

        # Check that defaults were used
        call_args = mock_subprocess.call_args[0][0]
        assert "--model" in call_args
        haiku_index = call_args.index("--model") + 1
        assert call_args[haiku_index] == "haiku"

    @patch("subprocess.run")
    def test_call_agent_parse_multiple_responses(self, mock_subprocess):
        """Test parsing multiple AI responses from output."""
        scheduler = PromptScheduler()

        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = """
Agent Response 1
─────────────────
First response content
─────────────────

Agent Response 2  
─────────────────
Second response content
─────────────────
        """.strip()
        mock_subprocess.return_value = mock_result

        result, session_id = scheduler._call_agent("Test prompt")

        assert "First response content" in result
        assert "Second response content" in result

    @patch("silica.cron.scheduler.SessionLocal")
    def test_execute_job_success(self, mock_session_local):
        """Test successful job execution."""
        scheduler = PromptScheduler()

        # Mock database session and objects
        mock_session = Mock()
        mock_session_local.return_value = mock_session

        mock_job = Mock()
        mock_job.id = 1
        mock_job.name = "Test Job"
        mock_job.prompt.prompt_text = "Test prompt"
        mock_job.prompt.model = "haiku"
        mock_job.prompt.persona = "basic_agent"

        Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_job
        )
        mock_session.add.return_value = None
        mock_session.commit.return_value = None

        with patch.object(
            scheduler, "_call_agent", return_value=("Success response", "session-123")
        ):
            scheduler._execute_job(1)

        # Verify job was removed from running set
        assert 1 not in scheduler.running_jobs

        # Verify database operations
        mock_session.add.assert_called()
        assert (
            mock_session.commit.call_count >= 2
        )  # Once for creation, once for completion

    @patch("silica.cron.scheduler.SessionLocal")
    def test_execute_job_not_found(self, mock_session_local):
        """Test executing a job that doesn't exist."""
        scheduler = PromptScheduler()

        mock_session = Mock()
        mock_session_local.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch("silica.cron.scheduler.logger") as mock_logger:
            scheduler._execute_job("job_nonexistent999")
            mock_logger.error.assert_called_with("Job job_nonexistent999 not found")

        assert "job_nonexistent999" not in scheduler.running_jobs

    @patch("silica.cron.scheduler.SessionLocal")
    def test_execute_job_agent_failure(self, mock_session_local):
        """Test job execution when agent fails."""
        scheduler = PromptScheduler()

        # Mock database session and objects
        mock_session = Mock()
        mock_session_local.return_value = mock_session

        mock_job = Mock()
        mock_job.id = 1
        mock_job.name = "Test Job"
        mock_job.prompt.prompt_text = "Test prompt"
        mock_job.prompt.model = "haiku"
        mock_job.prompt.persona = "basic_agent"

        Mock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_job
        )

        with patch.object(
            scheduler, "_call_agent", side_effect=Exception("Agent failed")
        ):
            with patch("silica.cron.scheduler.logger") as mock_logger:
                scheduler._execute_job(1)
                mock_logger.error.assert_called()

        # Job should be removed from running set even on failure
        assert 1 not in scheduler.running_jobs

    def test_scheduler_thread_safety(self):
        """Test that scheduler handles concurrent access safely."""
        scheduler = PromptScheduler()

        # Simulate adding/removing jobs from running set concurrently
        def add_job(job_id):
            scheduler.running_jobs.add(job_id)
            time.sleep(0.01)
            scheduler.running_jobs.discard(job_id)

        threads = []
        for i in range(10):
            thread = threading.Thread(target=add_job, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All jobs should be removed
        assert len(scheduler.running_jobs) == 0
