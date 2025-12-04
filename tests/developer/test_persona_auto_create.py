"""Tests for automatic persona creation when launching with a non-existent persona name."""

import pytest
from unittest.mock import patch, MagicMock


class TestPersonaAutoCreate:
    """Test that launching with a non-existent persona triggers creation flow."""

    def test_nonexistent_persona_triggers_interactive_creation(self, tmp_path):
        """When a non-existent persona name is provided, get_or_create should be called
        which allows interactive creation rather than failing with an error."""
        from silica.developer import personas

        # Patch the base directory to use temp dir
        with patch.object(personas, "_PERSONAS_BASE_DIRECTORY", tmp_path):
            # Create a mock console for interactive creation
            mock_console = MagicMock()
            # Simulate user declining template (creates blank persona)
            mock_console.input.return_value = "n"

            # Patch Console where it's imported in the function
            with patch("rich.console.Console", return_value=mock_console):
                # This should NOT raise an error - it should allow interactive creation
                persona = personas.get_or_create("new_custom_persona", interactive=True)

                # Verify persona was created
                assert persona is not None
                assert persona.base_directory == tmp_path / "new_custom_persona"
                # Verify persona directory exists
                assert (tmp_path / "new_custom_persona").exists()
                assert (tmp_path / "new_custom_persona" / "persona.md").exists()

    def test_nonexistent_persona_non_interactive_raises(self, tmp_path):
        """Non-interactive mode should raise ValueError for non-existent personas."""
        from silica.developer import personas

        with patch.object(personas, "_PERSONAS_BASE_DIRECTORY", tmp_path):
            with pytest.raises(ValueError) as exc_info:
                personas.get_or_create("nonexistent", interactive=False)

            assert "does not exist" in str(exc_info.value)

    def test_cyclopts_main_does_not_validate_against_builtins_only(
        self, tmp_path, monkeypatch
    ):
        """Ensure cyclopts_main doesn't reject persona names not in built-in list.

        The previous behavior was to check if persona_name was in available_personas
        (which only contained built-in names) and reject unknown ones. The new behavior
        allows get_or_create to handle non-existent personas interactively.
        """
        from silica.developer import personas

        # Patch persona base directory
        monkeypatch.setattr(personas, "_PERSONAS_BASE_DIRECTORY", tmp_path)

        # Create a persona directory to simulate an existing custom persona
        custom_persona_dir = tmp_path / "my_custom_persona"
        custom_persona_dir.mkdir(parents=True)
        (custom_persona_dir / "persona.md").write_text("Custom persona content")

        # Verify this custom persona is NOT in the built-in names
        builtin_names = personas.names()
        assert "my_custom_persona" not in builtin_names

        # But it should be loadable via get_or_create
        persona = personas.get_or_create("my_custom_persona", interactive=False)
        assert persona is not None
        assert persona.base_directory == custom_persona_dir

    def test_builtin_personas_still_work(self, tmp_path):
        """Ensure built-in personas still work correctly."""
        from silica.developer import personas

        with patch.object(personas, "_PERSONAS_BASE_DIRECTORY", tmp_path):
            # Built-in personas should work without creating files
            for builtin_name in personas.names():
                persona = personas.for_name(builtin_name)
                assert persona is not None
                # Should have a system_block for built-in personas
                assert persona.system_block is not None
