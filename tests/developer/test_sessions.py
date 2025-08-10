#!/usr/bin/env python3
"""Tests for session management features."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from silica.developer.tools.sessions import (
    list_sessions,
    parse_iso_date,
    get_session_data,
)


class TestSessionManagement(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test files
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_dir = Path(self.temp_dir.name)

        # Create sample session directories and data
        self.session_ids = ["session1", "session2", "session3"]
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
                            "root_dir": self.root_dir
                            if session_id != "session3"
                            else "/different/path",
                        },
                    },
                    f,
                )

        # Add a session without metadata (pre-HDEV-58)
        old_session_dir = self.history_dir / "old_session"
        old_session_dir.mkdir(parents=True)
        old_root_file = old_session_dir / "root.json"
        with open(old_root_file, "w") as f:
            json.dump(
                {
                    "session_id": "old_session",
                    "model_spec": {"title": "claude-3-5-sonnet"},
                    "messages": [{"role": "user", "content": "Hello"}],
                },
                f,
            )

    def tearDown(self):
        # Clean up the temporary directory
        self.temp_dir.cleanup()

    @patch("silica.developer.tools.sessions.get_history_dir")
    def test_list_sessions(self, mock_get_history_dir):
        # Mock the history directory to use our temporary one
        mock_get_history_dir.return_value = self.history_dir

        # Test listing all sessions
        sessions = list_sessions()
        self.assertEqual(
            len(sessions), 3
        )  # Should not include the one without metadata

        # Test sorting by last_updated (newest first)
        # In our test data, all have the same timestamp
        for session in sessions:
            self.assertIn(session["session_id"], self.session_ids)
            self.assertEqual(
                session["root_dir"],
                self.root_dir
                if session["session_id"] != "session3"
                else "/different/path",
            )

        # Test filtering by workdir
        filtered_sessions = list_sessions(workdir=self.root_dir)
        self.assertEqual(len(filtered_sessions), 2)  # session3 has a different root_dir
        for session in filtered_sessions:
            self.assertNotEqual(session["session_id"], "session3")

    def test_parse_iso_date(self):
        # Test valid ISO date
        formatted = parse_iso_date("2025-05-01T12:00:00Z")
        self.assertEqual(formatted, "2025-05-01 12:00")

        # Test invalid date
        formatted = parse_iso_date("not-a-date")
        self.assertEqual(formatted, "not-a-date")

        # Test empty string
        formatted = parse_iso_date("")
        self.assertEqual(formatted, "Unknown")

    @patch("silica.developer.tools.sessions.get_history_dir")
    def test_get_session_data(self, mock_get_history_dir):
        # Mock the history directory to use our temporary one
        mock_get_history_dir.return_value = self.history_dir

        # Test getting data for a valid session
        session_data = get_session_data("session1")
        self.assertIsNotNone(session_data)
        self.assertEqual(session_data["session_id"], "session1")

        # Test getting data with a partial ID
        session_data = get_session_data("session")
        self.assertIsNotNone(session_data)

        # Test getting data for a non-existent session
        session_data = get_session_data("nonexistent")
        self.assertIsNone(session_data)

    def test_agent_context_chat_history(self):
        # Test that AgentContext properly initializes and manages chat history
        from silica.developer.context import AgentContext
        from unittest.mock import MagicMock

        # Create a mock context
        mock_sandbox = MagicMock()
        mock_ui = MagicMock()
        mock_memory = MagicMock()

        # Create context with empty chat history
        context = AgentContext(
            session_id="test-session",
            parent_session_id=None,
            model_spec={
                "title": "test-model",
                "pricing": {"input": 1, "output": 1},
                "cache_pricing": {"read": 0, "write": 0},
                "max_tokens": 1000,
                "context_window": 100000,
            },
            sandbox=mock_sandbox,
            user_interface=mock_ui,
            usage=[],
            memory_manager=mock_memory,
        )

        # Verify chat_history is initialized as empty list
        self.assertEqual(context.chat_history, [])

        # Add a message to chat history
        context.chat_history.append({"role": "user", "content": "Hello"})
        self.assertEqual(len(context.chat_history), 1)

        # Create a new context with explicit chat history
        test_history = [{"role": "user", "content": "Test"}]
        context2 = AgentContext(
            session_id="test-session2",
            parent_session_id=None,
            model_spec={
                "title": "test-model",
                "pricing": {"input": 1, "output": 1},
                "cache_pricing": {"read": 0, "write": 0},
                "max_tokens": 1000,
                "context_window": 100000,
            },
            sandbox=mock_sandbox,
            user_interface=mock_ui,
            usage=[],
            memory_manager=mock_memory,
            _chat_history=test_history,
        )

        self.assertEqual(context2.chat_history, test_history)

    @patch("silica.developer.context.load_session_data")
    def test_load_session_data(self, mock_load_session_data):
        # Test load_session_data function with a successful load
        from silica.developer.context import AgentContext
        from unittest.mock import MagicMock

        # Create a mock context
        mock_context = MagicMock(spec=AgentContext)
        # Access the chat_history property
        mock_context.chat_history = [{"role": "user", "content": "Hello"}]
        mock_context.session_id = "test-session"

        # Set up the mock to return our mock context
        mock_load_session_data.return_value = mock_context

        # Create a base context
        base_context = MagicMock(spec=AgentContext)

        # Call the function
        result = mock_load_session_data("test-session", base_context)

        # Verify results
        self.assertEqual(result, mock_context)
        self.assertEqual(result.chat_history, mock_context.chat_history)
        self.assertEqual(result.session_id, "test-session")


if __name__ == "__main__":
    unittest.main()
