#!/usr/bin/env python3
"""Tests for session management with persona-based history locations."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from silica.developer.tools.sessions import (
    list_sessions,
    get_session_data,
    get_history_dir,
)
from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode


class TestPersonaBasedSessionManagement(unittest.TestCase):
    """Test that session tools work with persona-based history directories."""

    def setUp(self):
        # Create a temporary directory structure mimicking persona directories
        self.temp_dir = tempfile.TemporaryDirectory()
        self.persona_base_dir = Path(self.temp_dir.name) / "personas" / "test_persona"
        self.history_dir = self.persona_base_dir / "history"
        self.history_dir.mkdir(parents=True)

        # Create sample session directories and data
        self.session_ids = ["persona-session1", "persona-session2"]
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

    def test_get_history_dir_with_base(self):
        """Test that get_history_dir correctly uses persona base directory."""
        history_dir = get_history_dir(self.persona_base_dir)
        expected = self.persona_base_dir / "history"
        self.assertEqual(history_dir, expected)

    def test_get_history_dir_default(self):
        """Test that get_history_dir falls back to ~/.silica/personas/default when no base provided."""
        history_dir = get_history_dir()
        expected = Path.home() / ".silica" / "personas" / "default" / "history"
        self.assertEqual(history_dir, expected)

    def test_list_sessions_with_persona_base_dir(self):
        """Test listing sessions from persona-based history directory."""
        sessions = list_sessions(history_base_dir=self.persona_base_dir)
        self.assertEqual(len(sessions), 2)

        for session in sessions:
            self.assertIn(session["session_id"], self.session_ids)
            self.assertEqual(session["root_dir"], self.root_dir)

    def test_get_session_data_with_persona_base_dir(self):
        """Test getting session data from persona-based history directory."""
        session_data = get_session_data(
            "persona-session1", history_base_dir=self.persona_base_dir
        )
        self.assertIsNotNone(session_data)
        self.assertEqual(session_data["session_id"], "persona-session1")

    def test_list_sessions_tool_uses_context_history_base_dir(self):
        """Test that list_sessions_tool extracts history_base_dir from context."""
        from silica.developer.tools.sessions import list_sessions_tool

        # Create a mock context with history_base_dir set to persona directory
        mock_context = MagicMock()
        mock_context.history_base_dir = self.persona_base_dir

        # Call the tool
        result = list_sessions_tool(mock_context)

        # Verify the tool found the persona sessions (ID is truncated to 8 chars)
        self.assertIn("persona-", result)
        # Check for working directory which should be present
        self.assertIn("/path/to/project", result)
        # Check for table structure
        self.assertIn("Available Sessions", result)
        # Should have 2 rows (one for each session)
        result_lines = result.strip().split("\n")
        # Count lines that start with "| persona-" (data rows)
        data_rows = [
            line for line in result_lines if line.strip().startswith("| persona-")
        ]
        self.assertEqual(len(data_rows), 2)

    def test_get_session_tool_uses_context_history_base_dir(self):
        """Test that get_session_tool extracts history_base_dir from context."""
        from silica.developer.tools.sessions import get_session_tool

        # Create a mock context with history_base_dir set to persona directory
        mock_context = MagicMock()
        mock_context.history_base_dir = self.persona_base_dir

        # Call the tool
        result = get_session_tool(mock_context, session_id="persona-session1")

        # Verify the tool found the persona session
        self.assertIn("persona-session1", result)
        self.assertIn("Session Details", result)

    def test_agent_context_saves_to_persona_history(self):
        """Test that AgentContext saves history to persona-based directory."""
        # Create a mock user interface and sandbox
        mock_ui = MagicMock()
        mock_ui.permission_callback = MagicMock(return_value=True)
        mock_ui.permission_rendering_callback = MagicMock(return_value=True)

        # Create an AgentContext with persona base directory
        context = AgentContext.create(
            model_spec={
                "title": "test-model",
                "pricing": {"input": 1, "output": 1},
                "cache_pricing": {"read": 0, "write": 0},
                "max_tokens": 1000,
                "context_window": 100000,
            },
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=mock_ui,
            persona_base_directory=self.persona_base_dir,
        )

        # Create test chat history
        chat_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        # Flush the context (save history)
        context.flush(chat_history)

        # Verify the history file was created in the persona directory
        history_file = (
            self.persona_base_dir / "history" / context.session_id / "root.json"
        )
        self.assertTrue(history_file.exists())

        # Verify the content
        with open(history_file, "r") as f:
            data = json.load(f)
        self.assertEqual(data["session_id"], context.session_id)
        self.assertEqual(len(data["messages"]), 2)

    def test_list_sessions_tool_backward_compatible(self):
        """Test that list_sessions_tool works when context has no history_base_dir."""
        from silica.developer.tools.sessions import list_sessions_tool

        # Create a mock context without history_base_dir attribute
        mock_context = MagicMock(spec=[])

        # Should not raise an error, should use default
        result = list_sessions_tool(mock_context)

        # Result should be a string (may be empty if no sessions in default location)
        self.assertIsInstance(result, str)

    def test_sessions_tool_inside_agent_context(self):
        """Test that list_sessions_tool works correctly inside a running agent with context."""
        from silica.developer.tools.sessions import list_sessions_tool

        # Create a context with history_base_dir set
        mock_context = MagicMock()
        mock_context.history_base_dir = self.persona_base_dir

        # Call the tool
        result = list_sessions_tool(mock_context)

        # Verify it found the persona sessions
        self.assertIn("persona-", result)
        self.assertIn("Available Sessions", result)

    def test_get_session_tool_inside_agent_context(self):
        """Test that get_session_tool works correctly inside a running agent with context."""
        from silica.developer.tools.sessions import get_session_tool

        # Create a context with history_base_dir set
        mock_context = MagicMock()
        mock_context.history_base_dir = self.persona_base_dir

        # Call the tool
        result = get_session_tool(mock_context, session_id="persona-session1")

        # Verify it found the session
        self.assertIn("persona-session1", result)
        self.assertIn("Session Details", result)
        self.assertIn(self.root_dir, result)


if __name__ == "__main__":
    unittest.main()
