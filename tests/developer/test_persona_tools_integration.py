"""Integration tests for persona tools in the full agent context."""

import tempfile
from pathlib import Path

from silica.developer.toolbox import Toolbox
from silica.developer.context import AgentContext
from silica.developer.prompt import create_system_message
from silica.developer.models import get_model
from silica.developer.sandbox import SandboxMode
from silica.developer.user_interface import UserInterface


class MockUI(UserInterface):
    def handle_system_message(self, message: str, **kwargs):
        pass

    def handle_assistant_message(self, message: str, **kwargs):
        pass

    def permission_callback(self, action, resource, sandbox_mode, action_arguments):
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


def test_persona_tools_in_toolbox():
    """Test that persona tools are properly registered in the toolbox."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir) / "test_persona"
        persona_dir.mkdir()

        context = AgentContext.create(
            model_spec=get_model("sonnet"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=MockUI(),
            persona_base_directory=persona_dir,
        )

        toolbox = Toolbox(context)
        schemas = toolbox.schemas()
        schema_names = {s["name"] for s in schemas}

        # Verify all three persona tools are present
        assert "read_persona" in schema_names
        assert "write_persona" in schema_names
        assert "list_personas" in schema_names


def test_persona_workflow_integration():
    """Test the complete workflow: builtin -> write -> read -> system prompt refresh."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir) / "test_persona"
        persona_dir.mkdir()

        # Create context
        context = AgentContext.create(
            model_spec=get_model("sonnet"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=MockUI(),
            persona_base_directory=persona_dir,
        )

        toolbox = Toolbox(context)

        # Step 1: Start with built-in persona (no persona.md yet)
        builtin_content = "# Built-in Persona\nBe helpful."
        system_section = {"type": "text", "text": builtin_content}

        system_msg = create_system_message(
            context,
            system_section=system_section,
            include_sandbox=False,
            include_memory=False,
        )

        # Should use built-in wrapped in tags
        assert '<persona name="test_persona">' in system_msg[0]["text"]
        assert builtin_content in system_msg[0]["text"]

        # Step 2: Write a new persona using the tool
        new_content = "# Updated Persona\nBe concise."

        # Find write_persona function
        write_persona_func = next(
            (tool for tool in toolbox.agent_tools if tool.__name__ == "write_persona"),
            None,
        )
        assert write_persona_func is not None

        result = write_persona_func(context, content=new_content)
        assert "Successfully" in result

        # Step 3: Verify persona.md was created
        persona_file = persona_dir / "persona.md"
        assert persona_file.exists()
        assert persona_file.read_text() == new_content

        # Step 4: Read persona using tool
        read_persona_func = next(
            (tool for tool in toolbox.agent_tools if tool.__name__ == "read_persona"),
            None,
        )
        assert read_persona_func is not None

        result = read_persona_func(context)
        assert new_content in result

        # Step 5: Verify system prompt now uses persona.md (not built-in)
        system_msg = create_system_message(
            context,
            system_section=system_section,  # Still passing built-in
            include_sandbox=False,
            include_memory=False,
        )

        # Should use persona.md, not built-in
        assert new_content in system_msg[0]["text"]
        assert builtin_content not in system_msg[0]["text"]
        assert '<persona name="test_persona">' in system_msg[0]["text"]

        # Step 6: Test list_personas
        # Note: list_personas lists from global personas directory, not temp test dir
        # So we just verify it returns something valid
        list_personas_func = next(
            (tool for tool in toolbox.agent_tools if tool.__name__ == "list_personas"),
            None,
        )
        assert list_personas_func is not None

        result = list_personas_func(context)
        assert "Available Personas:" in result or "No personas" in result


def test_persona_backup_created():
    """Test that backups are created when updating persona."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir) / "test_persona"
        persona_dir.mkdir()

        context = AgentContext.create(
            model_spec=get_model("sonnet"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=MockUI(),
            persona_base_directory=persona_dir,
        )

        toolbox = Toolbox(context)
        write_persona = next(
            tool for tool in toolbox.agent_tools if tool.__name__ == "write_persona"
        )

        # Write initial persona
        write_persona(context, content="# Initial")

        # Update it
        result = write_persona(context, content="# Updated")

        # Check backup was created
        assert "Backup:" in result
        backups = list(persona_dir.glob("persona.backup.*.md"))
        assert len(backups) == 1
        assert backups[0].read_text() == "# Initial"


def test_persona_log_created():
    """Test that persona.log.jsonl is created and updated."""
    import json

    with tempfile.TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir) / "test_persona"
        persona_dir.mkdir()

        context = AgentContext.create(
            model_spec=get_model("sonnet"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=MockUI(),
            persona_base_directory=persona_dir,
        )

        toolbox = Toolbox(context)
        write_persona = next(
            tool for tool in toolbox.agent_tools if tool.__name__ == "write_persona"
        )

        # Write persona
        write_persona(context, content="# Test")

        # Check log file
        log_file = persona_dir / "persona.log.jsonl"
        assert log_file.exists()

        # Parse log entry
        with open(log_file, "r") as f:
            log_entry = json.loads(f.read())

        assert log_entry["action"] == "create"
        assert log_entry["persona_name"] == "test_persona"
        assert log_entry["content_length"] == 6
        assert "timestamp" in log_entry
