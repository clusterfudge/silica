"""Test that persona tools are conditionally available based on persona.md existence."""

import tempfile
from pathlib import Path

from silica.developer.toolbox import Toolbox
from silica.developer.context import AgentContext
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


def test_persona_tools_not_available_with_builtin_only():
    """Test that persona tools are NOT available when only built-in persona exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir) / "test_persona"
        persona_dir.mkdir()

        # Don't create persona.md - simulating built-in persona only

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

        # Persona tools should NOT be present
        assert "read_persona" not in schema_names
        assert "write_persona" not in schema_names


def test_persona_tools_available_with_persona_md():
    """Test that persona tools ARE available when persona.md exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir) / "test_persona"
        persona_dir.mkdir()

        # Create persona.md to enable persona tools
        persona_file = persona_dir / "persona.md"
        persona_file.write_text("# Custom Persona\nBe helpful.")

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

        # Persona tools SHOULD be present
        assert "read_persona" in schema_names
        assert "write_persona" in schema_names


def test_persona_tools_available_after_creating_file():
    """Test that tools become available after creating persona.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir) / "test_persona"
        persona_dir.mkdir()

        # First, no persona.md
        context1 = AgentContext.create(
            model_spec=get_model("sonnet"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=MockUI(),
            persona_base_directory=persona_dir,
        )

        toolbox1 = Toolbox(context1)
        schema_names1 = {s["name"] for s in toolbox1.schemas()}

        # Tools should NOT be available
        assert "read_persona" not in schema_names1
        assert "write_persona" not in schema_names1

        # Now create persona.md
        persona_file = persona_dir / "persona.md"
        persona_file.write_text("# Custom Persona")

        # Create new context and toolbox
        context2 = AgentContext.create(
            model_spec=get_model("sonnet"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=MockUI(),
            persona_base_directory=persona_dir,
        )

        toolbox2 = Toolbox(context2)
        schema_names2 = {s["name"] for s in toolbox2.schemas()}

        # Tools SHOULD now be available
        assert "read_persona" in schema_names2
        assert "write_persona" in schema_names2
