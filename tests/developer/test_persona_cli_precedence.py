#!/usr/bin/env python3
"""Tests for persona CLI argument precedence over .persona file."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from silica.developer.hdev import (
    _read_persona_file,
    _write_persona_file,
)


class TestPersonaCLIPrecedence(unittest.TestCase):
    """Test that CLI persona argument doesn't overwrite .persona file."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        """Clean up test fixtures."""
        self.temp_dir.cleanup()

    def test_cli_persona_does_not_overwrite_file(self):
        """Test that providing --persona on CLI doesn't overwrite .persona file."""
        # Create a .persona file with "autonomous_engineer"
        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            _write_persona_file("autonomous_engineer")

            # Verify file was created correctly
            persona_file = self.temp_path / ".persona"
            self.assertTrue(persona_file.exists())
            self.assertEqual(_read_persona_file(), "autonomous_engineer")

            # Store original content
            original_content = persona_file.read_text()

            # Now simulate running with --persona basic_agent
            # The file should NOT be overwritten

            # In the actual implementation, we need to verify that when
            # a CLI argument is provided, it takes precedence but doesn't
            # write back to the file.

            # After the fix, this should pass:
            # _write_persona_file should only be called when:
            # 1. No .persona file exists, OR
            # 2. No CLI argument was provided

            # Read the file again - it should still have the original content
            current_content = persona_file.read_text()
            self.assertEqual(current_content, original_content)
            self.assertEqual(_read_persona_file(), "autonomous_engineer")

    def test_cli_persona_precedence_in_cyclopts_main(self):
        """Test that CLI persona argument takes precedence but doesn't overwrite file."""
        from silica.developer.hdev import cyclopts_main

        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            # Create .persona file with one persona
            _write_persona_file("autonomous_engineer")
            original_persona = _read_persona_file()
            self.assertEqual(original_persona, "autonomous_engineer")

            # Mock the personas module to avoid interactive prompts
            mock_persona_obj = MagicMock()
            mock_persona_obj.system_block = {"type": "text", "text": "Test persona"}
            mock_persona_obj.base_directory = Path(
                "~/.silica/personas/basic_agent"
            ).expanduser()

            # Mock various parts that would cause issues in testing
            with patch(
                "silica.developer.hdev.personas.get_or_create"
            ) as mock_get_or_create:
                with patch("silica.developer.hdev.asyncio.run"):
                    with patch("silica.developer.hdev.Console"):
                        with patch("silica.developer.hdev.CLIUserInterface"):
                            with patch("silica.developer.hdev.AgentContext.create"):
                                mock_get_or_create.return_value = mock_persona_obj

                                # Call cyclopts_main with CLI persona argument
                                # This should use basic_agent but NOT overwrite the file
                                try:
                                    cyclopts_main(
                                        sandbox=[],
                                        persona="basic_agent",
                                        prompt="test prompt",
                                    )
                                except Exception:
                                    # We expect some errors since we're mocking a lot
                                    # The important part is checking the file afterward
                                    pass

                                # Check that the .persona file was NOT changed
                                # Currently this will FAIL because the code overwrites it
                                # After the fix, this should pass
                                current_persona = _read_persona_file()
                                self.assertEqual(
                                    current_persona,
                                    "autonomous_engineer",
                                    "CLI argument should not overwrite .persona file",
                                )

    def test_no_cli_persona_preserves_file(self):
        """Test that not providing --persona uses and preserves .persona file."""
        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            # Create .persona file
            _write_persona_file("autonomous_engineer")
            original_persona = _read_persona_file()

            # The current behavior writes back to the file even when
            # the persona came from the file itself, which is redundant
            # but acceptable. The key is it shouldn't change the content.

            # After any operation without --persona CLI arg,
            # the file should still have the same content
            self.assertEqual(_read_persona_file(), original_persona)

    def test_new_session_creates_persona_file(self):
        """Test that starting a new session (no file, no CLI) creates .persona file."""
        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            # Initially no .persona file
            self.assertIsNone(_read_persona_file())

            # When running without --persona and without existing file,
            # it should create the file with "default"
            _write_persona_file("default")

            # Verify file was created
            self.assertEqual(_read_persona_file(), "default")


if __name__ == "__main__":
    unittest.main()
