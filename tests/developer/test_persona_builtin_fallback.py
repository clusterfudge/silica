"""Test that built-in personas work as fallback when no persona.md exists."""

import tempfile
from pathlib import Path

from silica.developer.prompt import create_system_message
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


def test_builtin_persona_without_file():
    """Test that built-in persona is wrapped in tags when no persona.md exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir) / "test_persona"
        persona_dir.mkdir()

        # Don't create persona.md - should use built-in

        context = AgentContext.create(
            model_spec=get_model("sonnet"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=MockUI(),
            persona_base_directory=persona_dir,
        )

        # Create system message with a built-in persona
        builtin_content = "# Built-in Persona\n\nThis is a built-in."
        system_section = {"type": "text", "text": builtin_content}

        system_message = create_system_message(
            context,
            system_section=system_section,
            include_sandbox=False,
            include_memory=False,
        )

        # Should have the built-in wrapped in persona tags
        assert len(system_message) > 0
        first_section = system_message[0]
        assert '<persona name="test_persona">' in first_section["text"]
        assert builtin_content in first_section["text"]
        assert "</persona>" in first_section["text"]


def test_persona_file_overrides_builtin():
    """Test that persona.md takes precedence over built-in."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persona_dir = Path(tmpdir) / "test_persona"
        persona_dir.mkdir()

        # Write persona.md in memory/ subdirectory
        persona_content = "# From File"
        memory_dir = persona_dir / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / "persona.md").write_text(persona_content)

        context = AgentContext.create(
            model_spec=get_model("sonnet"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=MockUI(),
            persona_base_directory=persona_dir,
        )

        # Pass a built-in persona too
        builtin_content = "# Built-in Persona"
        system_section = {"type": "text", "text": builtin_content}

        system_message = create_system_message(
            context,
            system_section=system_section,
            include_sandbox=False,
            include_memory=False,
        )

        # Should use persona.md, not built-in
        assert len(system_message) > 0
        first_section = system_message[0]
        assert persona_content in first_section["text"]
        assert builtin_content not in first_section["text"]
        assert '<persona name="test_persona">' in first_section["text"]
