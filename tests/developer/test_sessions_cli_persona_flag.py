#!/usr/bin/env python3
"""Tests for CLI session commands with --persona flag."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from silica.developer.hdev import sessions, resume
from silica.developer.personas import Persona


class TestSessionsCLIWithPersonaFlag(unittest.TestCase):
    """Test that CLI session commands support --persona flag."""

    def setUp(self):
        # Create a temporary directory structure mimicking persona directories
        self.temp_dir = tempfile.TemporaryDirectory()
        self.persona_base_dir = Path(self.temp_dir.name) / "personas" / "test_persona"
        self.history_dir = self.persona_base_dir / "history"
        self.history_dir.mkdir(parents=True)

        # Create sample session directories and data
        self.session_ids = ["cli-session1", "cli-session2"]
        self.root_dir = "/path/to/project"

        # Create session directories
        for session_id in self.session_ids:
            session_dir = self.history_dir / session_id
            session_dir.mkdir(parents=True)

            # Create root.json with metadata
            root_file = session_dir / "root.json"
            with open(root_file, "w") as f:
                json.dump(
                    {
                        "session_id": session_id,
                        "model_spec": {"title": "claude-3-5-sonnet"},
                        "messages": [
                            {"role": "user", "content": "Hello"},
                            {"role": "assistant", "content": "Hi there!"},
                        ],
                        "metadata": {
                            "created_at": "2025-05-01T12:00:00Z",
                            "last_updated": "2025-05-01T12:30:00Z",
                            "root_dir": self.root_dir,
                        },
                    },
                    f,
                )

    def tearDown(self):
        # Clean up the temporary directory
        self.temp_dir.cleanup()

    @patch("silica.developer.hdev.personas.get_or_create")
    @patch("silica.developer.hdev.print_session_list")
    @patch("silica.developer.hdev.list_sessions")
    def test_sessions_command_with_persona_flag(
        self, mock_list_sessions, mock_print_session_list, mock_get_or_create
    ):
        """Test sessions command with --persona flag."""
        # Mock persona lookup
        mock_persona = Persona(
            system_block="Test persona", base_directory=self.persona_base_dir
        )
        mock_get_or_create.return_value = mock_persona

        # Mock session list
        mock_list_sessions.return_value = [
            {
                "session_id": "cli-session1",
                "root_dir": self.root_dir,
                "created_at": "2025-05-01T12:00:00Z",
                "last_updated": "2025-05-01T12:30:00Z",
                "message_count": 2,
            }
        ]

        # Call sessions command with persona
        sessions(workdir=None, persona="test_persona")

        # Verify persona was looked up with interactive=False
        mock_get_or_create.assert_called_once_with("test_persona", interactive=False)

        # Verify list_sessions was called with persona base directory
        mock_list_sessions.assert_called_once_with(
            workdir=None, history_base_dir=self.persona_base_dir
        )

        # Verify print was called
        mock_print_session_list.assert_called_once()

    @patch("silica.developer.hdev.personas.get_or_create")
    @patch("silica.developer.hdev.print_session_list")
    @patch("silica.developer.hdev.list_sessions")
    def test_sessions_command_without_persona_flag(
        self, mock_list_sessions, mock_print_session_list, mock_get_or_create
    ):
        """Test sessions command without --persona flag uses default location."""
        # Mock session list
        mock_list_sessions.return_value = []

        # Call sessions command without persona
        sessions(workdir=None, persona=None)

        # Verify persona lookup was NOT called
        mock_get_or_create.assert_not_called()

        # Verify list_sessions was called with no history_base_dir
        mock_list_sessions.assert_called_once_with(workdir=None, history_base_dir=None)

    @patch("silica.developer.hdev.personas.get_or_create")
    @patch("silica.developer.hdev.resume_session")
    def test_resume_command_with_persona_flag(
        self, mock_resume_session, mock_get_or_create
    ):
        """Test resume command with --persona flag."""
        # Mock persona lookup
        mock_persona = Persona(
            system_block="Test persona", base_directory=self.persona_base_dir
        )
        mock_get_or_create.return_value = mock_persona

        # Call resume command with persona
        resume(session_id="cli-session1", persona="test_persona")

        # Verify persona was looked up with interactive=False
        mock_get_or_create.assert_called_once_with("test_persona", interactive=False)

        # Verify resume_session was called with persona base directory
        mock_resume_session.assert_called_once_with(
            "cli-session1", history_base_dir=self.persona_base_dir
        )

    @patch("silica.developer.hdev.personas.get_or_create")
    @patch("silica.developer.hdev.resume_session")
    def test_resume_command_without_persona_flag(
        self, mock_resume_session, mock_get_or_create
    ):
        """Test resume command without --persona flag uses default location."""
        # Call resume command without persona
        resume(session_id="cli-session1", persona=None)

        # Verify persona lookup was NOT called
        mock_get_or_create.assert_not_called()

        # Verify resume_session was called with no history_base_dir
        mock_resume_session.assert_called_once_with(
            "cli-session1", history_base_dir=None
        )

    @patch("silica.developer.hdev.personas.get_or_create")
    @patch("silica.developer.hdev.print_session_list")
    @patch("silica.developer.hdev.list_sessions")
    def test_sessions_command_with_workdir_and_persona(
        self, mock_list_sessions, mock_print_session_list, mock_get_or_create
    ):
        """Test sessions command with both workdir and persona flags."""
        # Mock persona lookup
        mock_persona = Persona(
            system_block="Test persona", base_directory=self.persona_base_dir
        )
        mock_get_or_create.return_value = mock_persona

        # Mock session list
        mock_list_sessions.return_value = []

        # Call sessions command with both workdir and persona
        sessions(workdir="/some/path", persona="test_persona")

        # Verify persona was looked up
        mock_get_or_create.assert_called_once_with("test_persona", interactive=False)

        # Verify list_sessions was called with both workdir and history_base_dir
        mock_list_sessions.assert_called_once_with(
            workdir="/some/path", history_base_dir=self.persona_base_dir
        )


if __name__ == "__main__":
    unittest.main()
