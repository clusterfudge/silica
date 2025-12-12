"""
Tests for persona tools.
"""

import json
import pytest

from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode
from silica.developer.tools.persona_tools import (
    read_persona,
    write_persona,
)


@pytest.fixture
def temp_persona_dir(tmp_path, monkeypatch):
    """Create a temporary persona directory for testing."""
    persona_base = tmp_path / "personas"
    persona_base.mkdir()

    # Monkey patch the PERSONAS_BASE_DIRECTORY
    import silica.developer.personas

    monkeypatch.setattr(
        silica.developer.personas,
        "_PERSONAS_BASE_DIRECTORY",
        persona_base,
    )

    return persona_base


@pytest.fixture
def agent_context(temp_persona_dir):
    """Create a mock agent context with a test persona."""
    from silica.developer.user_interface import UserInterface
    from silica.developer.models import get_model

    # Create a test persona directory
    test_persona_dir = temp_persona_dir / "test_persona"
    test_persona_dir.mkdir()

    # Create a mock user interface
    class MockUI(UserInterface):
        def handle_system_message(self, message: str, **kwargs):
            pass

        def handle_assistant_message(self, message: str, **kwargs):
            pass

        def permission_callback(
            self, action, resource, sandbox_mode, action_arguments, group=None
        ):
            return True

        def permission_rendering_callback(self, action, resource, action_arguments):
            pass

        def handle_tool_use(self, tool_name, tool_params):
            pass

        def handle_tool_result(self, name, result, **kwargs):
            pass

        async def get_user_input(self, prompt=""):
            return ""

        def handle_user_input(self, user_input):
            pass

        def display_token_count(self, *args, **kwargs):
            pass

        def display_welcome_message(self):
            pass

        def status(self, message, spinner=None):
            from contextlib import contextmanager

            @contextmanager
            def dummy_context():
                yield

            return dummy_context()

        def bare(self, message, live=None):
            pass

    context = AgentContext.create(
        model_spec=get_model("sonnet"),
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=MockUI(),
        persona_base_directory=test_persona_dir,
    )

    return context


def test_read_persona_not_found(agent_context):
    """Test reading a persona that doesn't exist."""
    result = read_persona(agent_context)
    assert "Error" in result
    assert "not found" in result


def test_write_and_read_persona(agent_context, temp_persona_dir):
    """Test writing and reading a persona."""
    test_content = "# Test Persona\n\nThis is a test persona."

    # Write the persona
    result = write_persona(agent_context, content=test_content)
    assert "Successfully" in result
    assert "create" in result.lower()

    # Read it back
    result = read_persona(agent_context)
    assert test_content in result
    assert "test_persona" in result


def test_write_persona_creates_backup(agent_context, temp_persona_dir):
    """Test that writing a persona creates a backup of the old one."""
    # Write initial content
    initial_content = "# Initial Content"
    write_persona(agent_context, content=initial_content)

    # Write new content
    new_content = "# New Content"
    result = write_persona(agent_context, content=new_content)

    assert "Backup:" in result
    assert "Successfully write" in result

    # Check that backup file exists
    persona_dir = agent_context.history_base_dir
    backups = list(persona_dir.glob("persona.backup.*.md"))
    assert len(backups) == 1

    # Verify backup contains old content
    with open(backups[0], "r") as f:
        backup_content = f.read()
    assert backup_content == initial_content


def test_write_persona_empty_content(agent_context):
    """Test that writing empty content fails."""
    result = write_persona(agent_context, content="")
    assert "Error" in result
    assert "empty" in result.lower()


def test_write_persona_too_large(agent_context):
    """Test that writing content that's too large fails."""
    huge_content = "x" * 200000  # 200KB
    result = write_persona(agent_context, content=huge_content)
    assert "Error" in result
    assert "too large" in result.lower()


def test_log_persona_edit(agent_context, temp_persona_dir):
    """Test that persona edits are logged correctly."""
    persona_dir = agent_context.history_base_dir

    # Write a persona (which should log)
    content = "# Test"
    write_persona(agent_context, content=content)

    # Check log file exists and has correct format
    log_file = persona_dir / "persona.log.jsonl"
    assert log_file.exists()

    with open(log_file, "r") as f:
        lines = f.readlines()

    assert len(lines) == 1

    log_entry = json.loads(lines[0])
    assert "timestamp" in log_entry
    assert "action" in log_entry
    assert log_entry["action"] == "create"
    assert "persona_name" in log_entry
    assert log_entry["persona_name"] == "test_persona"
    assert "content_length" in log_entry
    assert log_entry["content_length"] == len(content)


def test_persona_refresh_on_edit(agent_context):
    """Test that editing persona and reloading shows new content."""
    from silica.developer.prompt import _load_persona_from_disk

    # Write initial persona
    initial = "# Initial"
    write_persona(agent_context, content=initial)

    # Load it
    section = _load_persona_from_disk(agent_context)
    assert initial in section["text"]

    # Update it
    updated = "# Updated"
    write_persona(agent_context, content=updated)

    # Load again - should show new content
    section = _load_persona_from_disk(agent_context)
    assert updated in section["text"]
    assert initial not in section["text"]
