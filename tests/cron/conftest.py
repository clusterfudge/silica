"""Pytest configuration for cron tests."""

import pytest
import tempfile
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from silica.cron.app import app
from silica.cron.models import Base, get_db, Prompt, ScheduledJob, JobExecution
from silica.cron.scheduler import PromptScheduler
from silica.cron.config.logging import configure_test_logging

# Configure test logging to suppress noise
configure_test_logging()


@pytest.fixture
def test_db():
    """Create a test database."""
    # Use temporary file instead of in-memory to avoid connection issues
    import tempfile
    import os

    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)  # Close file descriptor, just need path

    try:
        engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)

        TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=engine
        )

        def override_get_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        yield TestingSessionLocal
    finally:
        # Cleanup
        app.dependency_overrides.clear()
        if os.path.exists(db_path):
            os.unlink(db_path)


@pytest.fixture
def db_session(test_db):
    """Get a database session for testing."""
    session = test_db()
    yield session
    session.close()


@pytest.fixture
def client(test_db):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def sample_prompt(db_session):
    """Create a sample prompt for testing."""
    prompt = Prompt(
        name="Test Prompt",
        description="A test prompt for unit testing",
        prompt_text="Hello, this is a test prompt",
        model="haiku",
        persona="basic_agent",
    )
    db_session.add(prompt)
    db_session.commit()
    db_session.refresh(prompt)
    return prompt


@pytest.fixture
def sample_job(db_session, sample_prompt):
    """Create a sample scheduled job for testing."""
    job = ScheduledJob(
        name="Test Job",
        prompt_id=sample_prompt.id,
        cron_expression="0 9 * * *",  # Daily at 9 AM
        is_active=True,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def sample_execution(db_session, sample_job):
    """Create a sample job execution for testing."""
    execution = JobExecution(
        scheduled_job_id=sample_job.id,
        status="completed",
        session_id="test-session-123",
        output="Test execution output",
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)
    return execution


@pytest.fixture
def mock_scheduler():
    """Create a mock scheduler for testing."""
    with patch("silica.cron.scheduler.scheduler") as mock:
        mock_instance = MagicMock(spec=PromptScheduler)
        mock_instance._call_agent.return_value = ("Mocked response", "mock-session-id")
        mock._call_agent = mock_instance._call_agent
        yield mock_instance


@pytest.fixture
def temp_session_dir():
    """Create a temporary directory for session history testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create mock session structure
        session_id = "test-session-123"
        session_dir = os.path.join(temp_dir, ".hdev", "history", session_id)
        os.makedirs(session_dir, exist_ok=True)

        # Create mock session data with expected structure
        session_data = {
            "session_id": session_id,
            "title": "Test Session",
            "model_spec": {"title": "Test Model", "context_window": 8000},
            "metadata": {
                "created_at": "2024-01-01T12:00:00.000Z",
                "cli_args": ["hdev", "test"],
            },
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Test prompt"}]},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Test response"}],
                },
            ],
            "usage": [],
        }

        session_file = os.path.join(session_dir, "root.json")
        import json

        with open(session_file, "w") as f:
            json.dump(session_data, f)

        with patch("pathlib.Path.home", return_value=Path(temp_dir)):
            yield temp_dir, session_id, session_data
