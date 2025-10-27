#!/usr/bin/env python3
"""Tests for .persona file functionality."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from silica.developer.hdev import (
    _find_git_root,
    _get_persona_file_location,
    _read_persona_file,
    _write_persona_file,
    _ensure_persona_in_gitignore,
)


class TestPersonaFile(unittest.TestCase):
    """Test .persona file management."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        """Clean up test fixtures."""
        self.temp_dir.cleanup()

    def test_find_git_root_in_git_repo(self):
        """Test finding git root when in a git repository."""
        # Create a mock git repository
        git_dir = self.temp_path / ".git"
        git_dir.mkdir()

        # Create a subdirectory
        subdir = self.temp_path / "src" / "subdir"
        subdir.mkdir(parents=True)

        # Mock getcwd to return the subdirectory
        with patch("pathlib.Path.cwd", return_value=subdir):
            git_root = _find_git_root()
            # Resolve both paths to handle symlinks (e.g., /var vs /private/var on macOS)
            self.assertEqual(git_root.resolve(), self.temp_path.resolve())

    def test_find_git_root_not_in_git_repo(self):
        """Test finding git root when not in a git repository."""
        # No .git directory
        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            git_root = _find_git_root()
            self.assertIsNone(git_root)

    def test_get_persona_file_location_in_git_repo(self):
        """Test persona file location in a git repository."""
        # Create a mock git repository
        git_dir = self.temp_path / ".git"
        git_dir.mkdir()

        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            persona_file = _get_persona_file_location()
            # Resolve both paths to handle symlinks (e.g., /var vs /private/var on macOS)
            self.assertEqual(
                persona_file.resolve(), (self.temp_path / ".persona").resolve()
            )

    def test_get_persona_file_location_not_in_git_repo(self):
        """Test persona file location when not in a git repository."""
        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            persona_file = _get_persona_file_location()
            self.assertEqual(persona_file, self.temp_path / ".persona")

    def test_write_and_read_persona_file(self):
        """Test writing and reading persona file."""
        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            # Write persona name
            _write_persona_file("autonomous_engineer")

            # Read it back
            persona_name = _read_persona_file()
            self.assertEqual(persona_name, "autonomous_engineer")

            # Check file contents
            persona_file = self.temp_path / ".persona"
            self.assertTrue(persona_file.exists())
            content = persona_file.read_text()
            self.assertEqual(content.strip(), "autonomous_engineer")

    def test_read_persona_file_nonexistent(self):
        """Test reading persona file when it doesn't exist."""
        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            persona_name = _read_persona_file()
            self.assertIsNone(persona_name)

    def test_read_persona_file_empty(self):
        """Test reading persona file when it's empty."""
        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            # Create empty file
            persona_file = self.temp_path / ".persona"
            persona_file.write_text("")

            persona_name = _read_persona_file()
            self.assertIsNone(persona_name)

    def test_ensure_persona_in_gitignore_creates_gitignore(self):
        """Test that .persona is added to .gitignore."""
        # Create a mock git repository
        git_dir = self.temp_path / ".git"
        git_dir.mkdir()

        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            _ensure_persona_in_gitignore()

            gitignore_file = self.temp_path / ".gitignore"
            self.assertTrue(gitignore_file.exists())

            content = gitignore_file.read_text()
            self.assertIn(".persona", content)

    def test_ensure_persona_in_gitignore_appends_to_existing(self):
        """Test that .persona is appended to existing .gitignore."""
        # Create a mock git repository
        git_dir = self.temp_path / ".git"
        git_dir.mkdir()

        # Create existing .gitignore
        gitignore_file = self.temp_path / ".gitignore"
        gitignore_file.write_text("*.pyc\n__pycache__/\n")

        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            _ensure_persona_in_gitignore()

            content = gitignore_file.read_text()
            self.assertIn(".persona", content)
            self.assertIn("*.pyc", content)
            self.assertIn("__pycache__/", content)

    def test_ensure_persona_in_gitignore_already_present(self):
        """Test that .persona is not duplicated if already in .gitignore."""
        # Create a mock git repository
        git_dir = self.temp_path / ".git"
        git_dir.mkdir()

        # Create existing .gitignore with .persona already in it
        gitignore_file = self.temp_path / ".gitignore"
        original_content = "*.pyc\n.persona\n__pycache__/\n"
        gitignore_file.write_text(original_content)

        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            _ensure_persona_in_gitignore()

            content = gitignore_file.read_text()
            # Should not have duplicated .persona
            self.assertEqual(content.count(".persona"), 1)

    def test_ensure_persona_in_gitignore_not_in_git_repo(self):
        """Test that nothing happens when not in a git repository."""
        # No .git directory
        with patch("pathlib.Path.cwd", return_value=self.temp_path):
            _ensure_persona_in_gitignore()

            gitignore_file = self.temp_path / ".gitignore"
            # .gitignore should not be created
            self.assertFalse(gitignore_file.exists())

    def test_persona_file_location_in_subdirectory(self):
        """Test that .persona file is placed in git root even when launched from subdirectory."""
        # Create a mock git repository
        git_dir = self.temp_path / ".git"
        git_dir.mkdir()

        # Create a subdirectory
        subdir = self.temp_path / "src" / "subdir"
        subdir.mkdir(parents=True)

        # Mock getcwd to return the subdirectory
        with patch("pathlib.Path.cwd", return_value=subdir):
            # Write persona from subdirectory
            _write_persona_file("test_persona")

            # File should be in git root, not subdirectory
            persona_file_root = self.temp_path / ".persona"
            persona_file_subdir = subdir / ".persona"

            self.assertTrue(persona_file_root.exists())
            self.assertFalse(persona_file_subdir.exists())

            # Read it back
            persona_name = _read_persona_file()
            self.assertEqual(persona_name, "test_persona")


if __name__ == "__main__":
    unittest.main()
