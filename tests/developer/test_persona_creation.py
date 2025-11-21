"""
Tests for persona creation and selection functionality.
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from silica.developer import personas


@pytest.fixture
def temp_persona_dir(monkeypatch):
    """Create a temporary directory for personas during tests."""
    temp_dir = Path(tempfile.mkdtemp())
    # Monkey-patch the personas base directory
    monkeypatch.setattr(personas, "_PERSONAS_BASE_DIRECTORY", temp_dir)
    yield temp_dir
    # Clean up
    shutil.rmtree(temp_dir)


class TestPersonaModule:
    """Tests for the personas module functions."""

    def test_get_builtin_descriptions(self):
        """Test getting built-in persona descriptions."""
        descriptions = personas.get_builtin_descriptions()

        assert isinstance(descriptions, dict)
        assert "basic_agent" in descriptions
        assert "deep_research_agent" in descriptions
        assert "autonomous_engineer" in descriptions
        assert len(descriptions) >= 3

        # Check that descriptions are non-empty strings
        for name, desc in descriptions.items():
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_get_builtin_prompt(self):
        """Test getting built-in persona prompts."""
        # Test valid persona
        basic_prompt = personas.get_builtin_prompt("basic_agent")
        assert isinstance(basic_prompt, str)
        assert len(basic_prompt) > 0
        assert "helpful assistant" in basic_prompt.lower()

        # Test another valid persona
        engineer_prompt = personas.get_builtin_prompt("autonomous_engineer")
        assert isinstance(engineer_prompt, str)
        assert "software engineering" in engineer_prompt.lower()

        # Test invalid persona
        invalid_prompt = personas.get_builtin_prompt("nonexistent")
        assert invalid_prompt == ""

    def test_create_persona_directory(self, temp_persona_dir):
        """Test creating a persona directory."""
        persona_name = "test_persona"
        prompt_text = "This is a test persona prompt."

        # Create persona
        persona_dir = personas.create_persona_directory(persona_name, prompt_text)

        # Verify directory was created
        assert persona_dir.exists()
        assert persona_dir.is_dir()
        assert persona_dir == temp_persona_dir / persona_name

        # Verify persona.md was created in memory/ subdirectory with correct content
        persona_file = persona_dir / "memory" / "persona.md"
        assert persona_file.exists()
        with open(persona_file) as f:
            content = f.read()
        assert content == prompt_text

    def test_for_name_loads_persona_md(self, temp_persona_dir):
        """Test that for_name loads from persona.md when it exists."""
        persona_name = "custom_persona"
        custom_prompt = "This is my custom persona prompt."

        # Create persona with custom prompt in new location
        persona_dir = temp_persona_dir / persona_name
        memory_dir = persona_dir / "memory"
        memory_dir.mkdir(parents=True)
        persona_file = memory_dir / "persona.md"
        with open(persona_file, "w") as f:
            f.write(custom_prompt)

        # Load the persona
        persona = personas.for_name(persona_name)

        # Verify it loaded the custom prompt
        assert persona.system_block is not None
        assert persona.system_block["type"] == "text"
        assert custom_prompt in persona.system_block["text"]

    def test_for_name_uses_builtin_without_persona_md(self, temp_persona_dir):
        """Test that for_name uses built-in when no persona.md exists."""
        # Create directory without persona.md
        persona_name = "basic_agent"
        persona_dir = temp_persona_dir / persona_name
        persona_dir.mkdir(parents=True)

        # Load the persona
        persona = personas.for_name(persona_name)

        # Should use built-in basic_agent
        assert persona.system_block is not None
        assert "helpful assistant" in persona.system_block["text"].lower()

    def test_for_name_empty_persona_md(self, temp_persona_dir):
        """Test that for_name handles empty persona.md."""
        persona_name = "empty_persona"
        persona_dir = temp_persona_dir / persona_name
        memory_dir = persona_dir / "memory"
        memory_dir.mkdir(parents=True)
        persona_file = memory_dir / "persona.md"
        with open(persona_file, "w") as f:
            f.write("")  # Empty file

        # Load the persona
        persona = personas.for_name(persona_name)

        # Should have no system_block for empty file
        assert persona.system_block is None

    def test_create_persona_directory_blank(self, temp_persona_dir):
        """Test creating a blank persona directory."""
        persona_name = "blank_persona"

        # Create blank persona
        persona_dir = personas.create_persona_directory(persona_name, "")

        # Verify directory and file were created
        assert persona_dir.exists()
        persona_file = persona_dir / "memory" / "persona.md"
        assert persona_file.exists()

        # Verify file is empty
        with open(persona_file) as f:
            content = f.read()
        assert content == ""

    def test_create_persona_directory_idempotent(self, temp_persona_dir):
        """Test that creating a persona twice doesn't overwrite."""
        persona_name = "idempotent_test"
        original_text = "Original content"

        # Create persona first time
        personas.create_persona_directory(persona_name, original_text)

        # Try to create again with different content
        personas.create_persona_directory(persona_name, "New content")

        # Verify original content is preserved
        persona_file = temp_persona_dir / persona_name / "memory" / "persona.md"
        with open(persona_file) as f:
            content = f.read()
        assert content == original_text

    def test_persona_exists(self, temp_persona_dir):
        """Test checking if a persona exists."""
        persona_name = "exists_test"

        # Should not exist initially
        assert not personas.persona_exists(persona_name)

        # Create the persona
        personas.create_persona_directory(persona_name, "Test prompt")

        # Should exist now
        assert personas.persona_exists(persona_name)

        # Test with directory but no persona.md (template-based)
        template_name = "template_persona"
        template_dir = temp_persona_dir / template_name
        template_dir.mkdir()

        # Should exist (directory is sufficient)
        assert personas.persona_exists(template_name)


class TestPersonaIntegration:
    """Integration tests for persona creation workflow."""

    def test_persona_directory_structure(self, temp_persona_dir):
        """Test that persona directory structure is created correctly."""
        persona_name = "structure_test"
        prompt_text = "Test prompt for structure validation"

        persona_dir = personas.create_persona_directory(persona_name, prompt_text)

        # Check directory structure
        assert persona_dir.parent == temp_persona_dir
        assert persona_dir.name == persona_name

        # Check that memory directory was created
        memory_dir = persona_dir / "memory"
        assert memory_dir.exists()
        
        # Check files
        persona_file = memory_dir / "persona.md"
        assert persona_file.exists()
        assert persona_file.parent == memory_dir

        # History directory should be creatable by other components
        history_dir = persona_dir / "history"

        # This should be creatable without error
        history_dir.mkdir(exist_ok=True)

        assert history_dir.exists()


class TestGetOrCreate:
    """Tests for the get_or_create function."""

    def test_existing_persona_non_interactive(self, temp_persona_dir):
        """Test loading an existing persona in non-interactive mode."""
        persona_name = "existing"
        personas.create_persona_directory(persona_name, "Test prompt")

        result = personas.get_or_create(persona_name, interactive=False)

        assert isinstance(result, personas.Persona)
        assert result.base_directory == temp_persona_dir / persona_name
        assert result.system_block is not None

    def test_nonexistent_persona_non_interactive_raises(self, temp_persona_dir):
        """Test that non-existent persona raises error in non-interactive mode."""
        persona_name = "doesnotexist"

        with pytest.raises(ValueError, match="does not exist"):
            personas.get_or_create(persona_name, interactive=False)

    @patch("rich.console.Console")
    def test_create_blank_persona_interactive(
        self, mock_console_class, temp_persona_dir
    ):
        """Test creating a blank persona interactively."""
        persona_name = "new_blank"
        mock_console = MagicMock()
        mock_console_class.return_value = mock_console
        mock_console.input.return_value = "n"  # Decline template

        result = personas.get_or_create(persona_name, interactive=True)

        assert isinstance(result, personas.Persona)
        assert personas.persona_exists(persona_name)

        # Check that blank persona.md was created in memory/
        persona_file = temp_persona_dir / persona_name / "memory" / "persona.md"
        assert persona_file.exists()
        with open(persona_file) as f:
            content = f.read()
        assert content == ""

    @patch("prompt_toolkit.prompt")
    @patch("rich.console.Console")
    def test_create_from_template_interactive(
        self, mock_console_class, mock_pt_prompt, temp_persona_dir
    ):
        """Test creating a persona from template interactively."""
        persona_name = "from_template"
        mock_console = MagicMock()
        mock_console_class.return_value = mock_console
        mock_console.input.return_value = "y"  # Accept template
        mock_pt_prompt.return_value = "1"  # Choose first template

        result = personas.get_or_create(persona_name, interactive=True)

        assert isinstance(result, personas.Persona)
        assert personas.persona_exists(persona_name)

        # Check that persona.md contains built-in prompt in memory/
        persona_file = temp_persona_dir / persona_name / "memory" / "persona.md"
        assert persona_file.exists()
        with open(persona_file) as f:
            content = f.read()
        assert len(content) > 0
        # First template should be basic_agent
        assert "helpful assistant" in content.lower()

    @patch("rich.console.Console")
    def test_cancel_during_creation(self, mock_console_class, temp_persona_dir):
        """Test that cancellation raises KeyboardInterrupt."""
        persona_name = "cancelled"
        mock_console = MagicMock()
        mock_console_class.return_value = mock_console
        mock_console.input.side_effect = KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            personas.get_or_create(persona_name, interactive=True)

        # Persona should not be created
        assert not personas.persona_exists(persona_name)
