"""
Tests for persona creation and selection functionality.
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from rich.console import Console

from silica.developer import personas
from silica.developer.hdev import ensure_persona_exists


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

        # Verify persona.md was created with correct content
        persona_file = persona_dir / "persona.md"
        assert persona_file.exists()
        with open(persona_file) as f:
            content = f.read()
        assert content == prompt_text

    def test_create_persona_directory_blank(self, temp_persona_dir):
        """Test creating a blank persona directory."""
        persona_name = "blank_persona"

        # Create blank persona
        persona_dir = personas.create_persona_directory(persona_name, "")

        # Verify directory and file were created
        assert persona_dir.exists()
        persona_file = persona_dir / "persona.md"
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
        persona_file = temp_persona_dir / persona_name / "persona.md"
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

        # Test with missing persona.md
        incomplete_name = "incomplete"
        incomplete_dir = temp_persona_dir / incomplete_name
        incomplete_dir.mkdir()

        # Should not exist (missing persona.md)
        assert not personas.persona_exists(incomplete_name)


class TestEnsurePersonaExists:
    """Tests for the ensure_persona_exists function."""

    def test_existing_persona(self, temp_persona_dir):
        """Test with an already existing persona."""
        persona_name = "existing"
        personas.create_persona_directory(persona_name, "Test prompt")

        console = Console()
        result = ensure_persona_exists(persona_name, console)

        assert result is True

    @patch("silica.developer.hdev.pt_prompt")
    def test_create_blank_persona_no_template(self, mock_prompt, temp_persona_dir):
        """Test creating a blank persona when user declines template."""
        persona_name = "new_blank"
        console = MagicMock()

        # Mock user saying 'n' to template question
        console.input.return_value = "n"

        result = ensure_persona_exists(persona_name, console)

        assert result is True
        assert personas.persona_exists(persona_name)

        # Check that file is blank
        persona_file = temp_persona_dir / persona_name / "persona.md"
        with open(persona_file) as f:
            content = f.read()
        assert content == ""

    @patch("silica.developer.hdev.pt_prompt")
    def test_create_persona_from_template(self, mock_prompt, temp_persona_dir):
        """Test creating a persona from a built-in template."""
        persona_name = "from_template"
        console = MagicMock()

        # Mock user saying 'y' to template, then choosing option 1
        console.input.return_value = "y"
        mock_prompt.return_value = "1"

        result = ensure_persona_exists(persona_name, console)

        assert result is True
        assert personas.persona_exists(persona_name)

        # Check that file contains the basic_agent prompt
        persona_file = temp_persona_dir / persona_name / "persona.md"
        with open(persona_file) as f:
            content = f.read()
        assert len(content) > 0
        assert "helpful assistant" in content.lower()

    @patch("silica.developer.hdev.pt_prompt")
    def test_create_blank_from_template_menu(self, mock_prompt, temp_persona_dir):
        """Test creating blank persona by selecting blank option from menu."""
        persona_name = "blank_from_menu"
        console = MagicMock()

        # Mock user saying 'y' to template, then choosing the blank option (4)
        console.input.return_value = "y"
        builtin_count = len(personas.get_builtin_descriptions())
        mock_prompt.return_value = str(builtin_count + 1)

        result = ensure_persona_exists(persona_name, console)

        assert result is True
        assert personas.persona_exists(persona_name)

        # Check that file is blank
        persona_file = temp_persona_dir / persona_name / "persona.md"
        with open(persona_file) as f:
            content = f.read()
        assert content == ""

    def test_cancel_on_template_question(self, temp_persona_dir):
        """Test cancelling during template question."""
        persona_name = "cancelled"
        console = MagicMock()

        # Mock user pressing Ctrl+C
        console.input.side_effect = KeyboardInterrupt()

        result = ensure_persona_exists(persona_name, console)

        assert result is False
        assert not personas.persona_exists(persona_name)

    @patch("silica.developer.hdev.pt_prompt")
    def test_cancel_on_choice_prompt(self, mock_prompt, temp_persona_dir):
        """Test cancelling during choice selection."""
        persona_name = "cancelled_choice"
        console = MagicMock()

        # Mock user saying 'y' to template, then Ctrl+C on choice
        console.input.return_value = "y"
        mock_prompt.side_effect = KeyboardInterrupt()

        result = ensure_persona_exists(persona_name, console)

        assert result is False
        assert not personas.persona_exists(persona_name)


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

        # Check files
        persona_file = persona_dir / "persona.md"
        assert persona_file.exists()
        assert persona_file.parent == persona_dir

        # Memory and history directories should be created by other components
        # but the base persona directory should be ready
        memory_dir = persona_dir / "memory"
        history_dir = persona_dir / "history"

        # These should be creatable without error
        memory_dir.mkdir(exist_ok=True)
        history_dir.mkdir(exist_ok=True)

        assert memory_dir.exists()
        assert history_dir.exists()
