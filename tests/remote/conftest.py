"""Test configuration and fixtures for remote tests."""

import subprocess
import pytest
import tempfile
import os
from pathlib import Path


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "tmux: marks tests that use tmux sessions")
    config.addinivalue_line("markers", "cleanup: marks tests that need cleanup")


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_tmux_sessions():
    """Clean up any test tmux sessions at start and end of test session."""

    def cleanup_sessions():
        """Clean up any tmux sessions starting with 'test-'."""
        try:
            # List all sessions
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0 and result.stdout.strip():
                sessions = result.stdout.strip().split("\n")

                # Kill any test sessions
                for session in sessions:
                    if session.startswith("test-"):
                        subprocess.run(
                            ["tmux", "kill-session", "-t", session],
                            capture_output=True,
                            check=False,
                        )
                        print(f"Cleaned up test tmux session: {session}")

        except FileNotFoundError:
            # tmux not available, nothing to clean
            pass

    # Clean up at start
    cleanup_sessions()

    yield

    # Clean up at end
    cleanup_sessions()


@pytest.fixture
def isolated_workspace():
    """Create an isolated workspace for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        original_cwd = os.getcwd()
        original_env = dict(os.environ)

        try:
            # Change to temp directory
            os.chdir(temp_dir)

            # Set test environment
            os.environ["WORKSPACE_NAME"] = "test-isolated"

            yield Path(temp_dir)

        finally:
            # Restore original state
            os.chdir(original_cwd)
            os.environ.clear()
            os.environ.update(original_env)


@pytest.fixture
def tmux_available():
    """Check if tmux is available for testing."""
    try:
        subprocess.run(["tmux", "-V"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("tmux not available")


@pytest.fixture
def test_session_name():
    """Generate a unique test session name."""
    import uuid

    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def cleanup_test_session():
    """Fixture that ensures a specific test session is cleaned up."""
    session_name = None

    def set_session_name(name):
        nonlocal session_name
        session_name = name

    yield set_session_name

    # Cleanup after test
    if session_name:
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True,
                check=False,
            )
        except FileNotFoundError:
            pass
