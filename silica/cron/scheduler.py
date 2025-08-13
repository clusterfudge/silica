"""Cron scheduler for executing agent prompts."""

import threading
import time
import subprocess
import uuid
from datetime import datetime
from typing import Set
from croniter import croniter
import logging

from .models import SessionLocal, ScheduledJob, JobExecution

logger = logging.getLogger(__name__)


class PromptScheduler:
    """Scheduler for running cron-scheduled prompts."""

    def __init__(self, agent_model: str = "haiku", agent_timeout: int = 300):
        """Initialize the scheduler.

        Args:
            agent_model: Model to use for agent (haiku, sonnet, sonnet-3.5, opus)
            agent_timeout: Timeout for agent execution in seconds (default: 5 minutes)
        """
        self.agent_model = agent_model
        self.silica_timeout = agent_timeout
        self.running_jobs: Set[int] = set()
        self.scheduler_thread: threading.Thread = None
        self.stop_event = threading.Event()

    def start(self):
        """Start the scheduler in a background thread."""
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            logger.warning("Scheduler is already running")
            return

        self.stop_event.clear()
        self.scheduler_thread = threading.Thread(
            target=self._run_scheduler, daemon=True
        )
        self.scheduler_thread.start()
        logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler."""
        self.stop_event.set()
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=5)
        logger.info("Scheduler stopped")

    def _run_scheduler(self):
        """Main scheduler loop."""
        logger.info("Scheduler loop started")

        while not self.stop_event.is_set():
            try:
                self._check_and_execute_jobs()
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)
                time.sleep(60)  # Wait longer on error

    def _check_and_execute_jobs(self):
        """Check for jobs that need to be executed and run them."""
        db = SessionLocal()
        try:
            # Get all active jobs
            jobs = db.query(ScheduledJob).filter(ScheduledJob.is_active).all()

            for job in jobs:
                if self._should_run_job(job):
                    if job.id not in self.running_jobs:
                        # Start job execution in background
                        threading.Thread(
                            target=self._execute_job, args=(job.id,), daemon=True
                        ).start()
                    else:
                        logger.info(
                            f"Job {job.id} ({job.name}) is already running, skipping"
                        )

        except Exception as e:
            logger.error(f"Error checking jobs: {e}", exc_info=True)
        finally:
            db.close()

    def _should_run_job(self, job: ScheduledJob) -> bool:
        """Check if a job should run now based on its cron expression."""
        try:
            cron = croniter(job.cron_expression, datetime.now())
            # Get the previous scheduled time
            prev_time = cron.get_prev(datetime)

            # Check if we're within the execution window (last 30 seconds)
            now = datetime.now()
            time_diff = (now - prev_time).total_seconds()

            # Run if the job was scheduled within the last 30 seconds
            return 0 <= time_diff <= 30
        except Exception as e:
            logger.error(f"Error checking cron expression for job {job.id}: {e}")
            return False

    def _execute_job(self, job_id: int):
        """Execute a specific job."""
        self.running_jobs.add(job_id)
        db = SessionLocal()

        try:
            # Get job details
            job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
            if not job:
                logger.error(f"Job {job_id} not found")
                return

            # Create execution record
            execution = JobExecution(scheduled_job_id=job_id, status="running")
            db.add(execution)
            db.commit()

            logger.info(f"Executing job {job_id} ({job.name})")

            try:
                # Execute the prompt via silica agent with prompt-specific settings
                response, session_id = self._call_agent(
                    prompt=job.prompt.prompt_text,
                    model=job.prompt.model,
                    persona=job.prompt.persona,
                )

                # Update execution with success
                execution.completed_at = datetime.now()
                execution.status = "completed"
                execution.output = response
                execution.session_id = session_id
                db.commit()

                logger.info(
                    f"Job {job_id} completed successfully with session {session_id}"
                )

            except Exception as e:
                # Update execution with error
                execution.completed_at = datetime.now()
                execution.status = "failed"
                execution.error_message = str(e)
                db.commit()

                logger.error(f"Job {job_id} failed: {e}")

        except Exception as e:
            logger.error(f"Error executing job {job_id}: {e}", exc_info=True)
        finally:
            self.running_jobs.discard(job_id)
            db.close()

    def _call_agent(
        self, prompt: str, model: str = None, persona: str = None
    ) -> tuple[str, str]:
        """Execute a prompt using si (silica developer CLI).

        Returns:
            tuple: (output, session_id)
        """
        try:
            # Use provided model or fall back to default
            agent_model = model or self.agent_model

            # Generate unique session ID for this execution
            session_id = str(uuid.uuid4())

            # Create a temporary directory for this execution
            import tempfile

            with tempfile.TemporaryDirectory() as temp_dir:
                # Build silica command
                cmd = [
                    "silica",
                    "--prompt",
                    prompt,
                    "--model",
                    agent_model,
                    "--sandbox-mode",
                    "ALLOW_ALL",  # Allow all operations without prompts
                    "--session-id",
                    session_id,
                    "--disable-compaction",  # Keep full conversation
                ]

                # Add persona if specified
                if persona:
                    cmd.extend(["--persona", persona])

                # Add sandbox directory
                cmd.append(temp_dir)

                logger.info(
                    f"Executing silica with model {agent_model}, persona {persona}: {prompt[:100]}..."
                )

                # Execute agent with timeout
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=self.silica_timeout
                )

                if result.returncode == 0:
                    # Extract all AI responses from the output
                    output = result.stdout

                    # Parse the output to extract all AI responses
                    # silica output contains various sections separated by lines of ─
                    lines = output.split("\n")
                    ai_responses = []
                    current_response_lines = []
                    in_ai_section = False

                    for line in lines:
                        if "Agent" in line and "─" in line:
                            # Start of new AI section
                            if current_response_lines and in_ai_section:
                                # Save previous response
                                response_text = "\n".join(
                                    current_response_lines
                                ).strip()
                                if response_text:
                                    ai_responses.append(response_text)
                            current_response_lines = []
                            in_ai_section = True
                            continue
                        elif line.strip().startswith("─") and in_ai_section:
                            # End of current AI section
                            if current_response_lines:
                                response_text = "\n".join(
                                    current_response_lines
                                ).strip()
                                if response_text:
                                    ai_responses.append(response_text)
                            current_response_lines = []
                            in_ai_section = False
                        elif in_ai_section:
                            current_response_lines.append(line)

                    # Handle case where the last section doesn't end with ─
                    if current_response_lines and in_ai_section:
                        response_text = "\n".join(current_response_lines).strip()
                        if response_text:
                            ai_responses.append(response_text)

                    if ai_responses:
                        # Combine all AI responses
                        full_response = "\n\n".join(ai_responses)
                        return full_response, session_id
                    else:
                        # Fallback to full output if parsing fails
                        return output, session_id
                else:
                    error_msg = result.stderr or result.stdout
                    raise Exception(
                        f"silica execution failed (exit code {result.returncode}): {error_msg}"
                    )

        except subprocess.TimeoutExpired:
            # Note: session_id is still available even if timeout occurs
            raise Exception(
                f"silica execution timed out after {self.silica_timeout} seconds"
            )
        except subprocess.SubprocessError as e:
            raise Exception(f"Failed to execute silica: {e}")
        except Exception as e:
            logger.error(f"Error in silica execution: {e}")
            raise Exception(f"silica execution error: {e}")


# Global scheduler instance
scheduler = PromptScheduler()
