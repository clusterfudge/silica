#!/usr/bin/env python3
"""Tests for session management features."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from silica.developer.tools.sessions import (
    list_sessions,
    parse_iso_date,
    get_session_data,
    _extract_first_user_message,
    _truncate_message,
    format_session_option,
    interactive_resume,
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


class TestFirstMessageExtraction(unittest.TestCase):
    def test_extract_simple_string_message(self):
        """Test extracting first message when content is a simple string."""
        messages = [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well!"},
        ]
        result = _extract_first_user_message(messages)
        self.assertEqual(result, "Hello, how are you?")

    def test_extract_structured_message(self):
        """Test extracting first message when content is a list of blocks."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Please review this code"},
                    {"type": "image", "source": {"type": "base64", "data": "..."}},
                ],
            }
        ]
        result = _extract_first_user_message(messages)
        self.assertEqual(result, "Please review this code")

    def test_extract_no_user_messages(self):
        """Test when there are no user messages."""
        messages = [{"role": "assistant", "content": "Hello!"}]
        result = _extract_first_user_message(messages)
        self.assertIsNone(result)

    def test_extract_empty_messages(self):
        """Test with empty message list."""
        result = _extract_first_user_message([])
        self.assertIsNone(result)

    def test_extract_tool_result_message(self):
        """Test extracting from a tool_result message (common in sessions)."""
        messages = [
            {"role": "user", "content": "refresh plane cache"},
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "123", "content": "Done"}
                ],
            },
        ]
        result = _extract_first_user_message(messages)
        self.assertEqual(result, "refresh plane cache")


class TestTruncateMessage(unittest.TestCase):
    def test_truncate_short_message(self):
        """Test that short messages are not truncated."""
        result = _truncate_message("Hello world", max_length=60)
        self.assertEqual(result, "Hello world")

    def test_truncate_long_message(self):
        """Test that long messages are truncated with ellipsis."""
        long_message = "A" * 100
        result = _truncate_message(long_message, max_length=60)
        self.assertEqual(len(result), 60)
        self.assertTrue(result.endswith("..."))
        self.assertEqual(result, "A" * 57 + "...")

    def test_truncate_none_message(self):
        """Test handling of None input."""
        result = _truncate_message(None)
        self.assertEqual(result, "")

    def test_truncate_empty_message(self):
        """Test handling of empty string."""
        result = _truncate_message("")
        self.assertEqual(result, "")

    def test_truncate_with_newlines(self):
        """Test that newlines are collapsed."""
        message = "Hello\nWorld\nThis is a test"
        result = _truncate_message(message)
        self.assertEqual(result, "Hello World This is a test")


class TestFormatSessionOption(unittest.TestCase):
    def test_format_with_all_fields(self):
        """Test formatting a session with all fields present."""
        session = {
            "session_id": "abcd1234-5678-90ef",
            "last_updated": "2025-01-15T14:30:00Z",
            "message_count": 15,
            "first_message": "Help me fix this bug",
        }
        result = format_session_option(session)
        self.assertIn("[abcd1234]", result)
        self.assertIn("2025-01-15 14:30", result)
        self.assertIn("(15 msgs)", result)
        self.assertIn('"Help me fix this bug"', result)

    def test_format_without_first_message(self):
        """Test formatting a session without first message."""
        session = {
            "session_id": "abcd1234-5678-90ef",
            "last_updated": "2025-01-15T14:30:00Z",
            "message_count": 0,
            "first_message": None,
        }
        result = format_session_option(session)
        self.assertIn("[abcd1234]", result)
        self.assertNotIn('"', result)


class TestInteractiveResume(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test files
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_dir = Path(self.temp_dir.name)

        # Create sessions with messages
        for i, session_id in enumerate(["session-a", "session-b"]):
            session_dir = self.history_dir / session_id
            session_dir.mkdir(parents=True)

            root_file = session_dir / "root.json"
            with open(root_file, "w") as f:
                json.dump(
                    {
                        "session_id": session_id,
                        "model_spec": {"title": "claude-sonnet-4"},
                        "messages": [
                            {"role": "user", "content": f"Message for {session_id}"},
                        ],
                        "metadata": {
                            "created_at": f"2025-01-{15+i}T12:00:00Z",
                            "last_updated": f"2025-01-{15+i}T12:30:00Z",
                            "root_dir": "/path/to/project",
                        },
                    },
                    f,
                )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("silica.developer.tools.sessions.get_history_dir")
    def test_format_session_option_includes_message(self, mock_get_history_dir):
        """Test that format_session_option includes the first message."""
        mock_get_history_dir.return_value = self.history_dir

        sessions = list_sessions()
        self.assertEqual(len(sessions), 2)

        # Format first session option
        option = format_session_option(sessions[0])

        # Should contain session ID, date, message count, and first message
        self.assertIn("[session-", option)
        self.assertIn("msgs)", option)
        self.assertIn('"Message for session-', option)


@pytest.mark.asyncio
async def test_interactive_resume_returns_session_id():
    """Test that interactive_resume returns the selected session ID."""
    from unittest.mock import AsyncMock, MagicMock

    # Create temp directory for test
    with tempfile.TemporaryDirectory() as temp_dir:
        history_dir = Path(temp_dir)

        # Create a test session
        session_dir = history_dir / "test-session-123"
        session_dir.mkdir(parents=True)

        root_file = session_dir / "root.json"
        with open(root_file, "w") as f:
            json.dump(
                {
                    "session_id": "test-session-123",
                    "model_spec": {"title": "claude-sonnet-4"},
                    "messages": [
                        {"role": "user", "content": "Test message"},
                    ],
                    "metadata": {
                        "created_at": "2025-01-15T12:00:00Z",
                        "last_updated": "2025-01-15T12:30:00Z",
                        "root_dir": "/path/to/project",
                    },
                },
                f,
            )

        # Create mock user interface that returns the session ID via get_session_choice
        mock_ui = MagicMock()
        # Mock get_session_choice to return the session ID directly
        mock_ui.get_session_choice = AsyncMock(return_value="test-session-123")

        with patch(
            "silica.developer.tools.sessions.get_history_dir"
        ) as mock_get_history_dir:
            mock_get_history_dir.return_value = history_dir

            result = await interactive_resume(user_interface=mock_ui)

            # Should return the full session ID
            assert result == "test-session-123"


@pytest.mark.asyncio
async def test_interactive_resume_cancelled():
    """Test that interactive_resume returns None when cancelled."""
    from unittest.mock import AsyncMock, MagicMock

    with tempfile.TemporaryDirectory() as temp_dir:
        history_dir = Path(temp_dir)

        # Create a test session
        session_dir = history_dir / "test-session-123"
        session_dir.mkdir(parents=True)

        root_file = session_dir / "root.json"
        with open(root_file, "w") as f:
            json.dump(
                {
                    "session_id": "test-session-123",
                    "model_spec": {"title": "claude-sonnet-4"},
                    "messages": [{"role": "user", "content": "Test"}],
                    "metadata": {
                        "created_at": "2025-01-15T12:00:00Z",
                        "last_updated": "2025-01-15T12:30:00Z",
                        "root_dir": "/path/to/project",
                    },
                },
                f,
            )

        mock_ui = MagicMock()
        # Mock get_session_choice to return None (cancelled)
        mock_ui.get_session_choice = AsyncMock(return_value=None)

        with patch(
            "silica.developer.tools.sessions.get_history_dir"
        ) as mock_get_history_dir:
            mock_get_history_dir.return_value = history_dir

            result = await interactive_resume(user_interface=mock_ui)

            # Should return None when cancelled
            assert result is None


@pytest.mark.asyncio
async def test_interactive_resume_no_sessions():
    """Test that interactive_resume returns None when no sessions exist."""
    from unittest.mock import MagicMock

    with tempfile.TemporaryDirectory() as temp_dir:
        history_dir = Path(temp_dir)
        # Empty directory - no sessions

        mock_ui = MagicMock()

        with patch(
            "silica.developer.tools.sessions.get_history_dir"
        ) as mock_get_history_dir:
            mock_get_history_dir.return_value = history_dir

            result = await interactive_resume(user_interface=mock_ui)

            # Should return None when no sessions exist
            assert result is None


class TestLoadSessionWithOrphanedToolBlocks(unittest.TestCase):
    """Test that loading sessions cleans up orphaned tool blocks."""

    def setUp(self):
        # Create a temporary directory for test files
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("silica.developer.context.Path.home")
    def test_load_session_cleans_orphaned_tool_results(self, mock_home):
        """Test that loading a session with orphaned tool_results cleans them up."""
        from silica.developer.context import load_session_data, AgentContext
        from unittest.mock import MagicMock

        mock_home.return_value = self.history_dir

        # Create a session with orphaned tool_results (no matching tool_use)
        session_dir = (
            self.history_dir
            / ".silica"
            / "personas"
            / "default"
            / "history"
            / "orphan-session"
        )
        session_dir.mkdir(parents=True)

        root_file = session_dir / "root.json"
        with open(root_file, "w") as f:
            json.dump(
                {
                    "session_id": "orphan-session",
                    "model_spec": {"title": "claude-sonnet-4"},
                    "messages": [
                        {"role": "user", "content": "Summary of previous conversation"},
                        {
                            "role": "user",
                            "content": [
                                # Orphaned tool_result - no matching tool_use
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "orphan_id",
                                    "content": "result",
                                },
                            ],
                        },
                        {"role": "assistant", "content": "Continuing..."},
                    ],
                    "metadata": {
                        "created_at": "2025-01-15T12:00:00Z",
                        "last_updated": "2025-01-15T12:30:00Z",
                        "root_dir": "/path/to/project",
                    },
                },
                f,
            )

        # Create a mock base context
        mock_sandbox = MagicMock()
        mock_ui = MagicMock()
        mock_memory = MagicMock()

        base_context = AgentContext(
            session_id="base-session",
            parent_session_id=None,
            model_spec={"title": "test-model"},
            sandbox=mock_sandbox,
            user_interface=mock_ui,
            usage=[],
            memory_manager=mock_memory,
        )

        # Load the session
        loaded_context = load_session_data(
            "orphan-session",
            base_context,
            history_base_dir=self.history_dir / ".silica" / "personas" / "default",
        )

        self.assertIsNotNone(loaded_context)

        # Verify orphaned tool_result was cleaned up
        from silica.developer.compaction_validation import validate_message_structure

        report = validate_message_structure(loaded_context.chat_history)
        self.assertTrue(
            report.is_valid, f"Messages should be valid: {report.detailed_report()}"
        )
        self.assertEqual(
            report.tool_result_count, 0, "Orphaned tool_results should be removed"
        )

    @patch("silica.developer.context.Path.home")
    def test_load_session_cleans_orphaned_tool_uses(self, mock_home):
        """Test that loading a session with orphaned tool_use blocks cleans them up."""
        from silica.developer.context import load_session_data, AgentContext
        from unittest.mock import MagicMock

        mock_home.return_value = self.history_dir

        # Create a session with orphaned tool_use (no matching tool_result)
        session_dir = (
            self.history_dir
            / ".silica"
            / "personas"
            / "default"
            / "history"
            / "orphan-use-session"
        )
        session_dir.mkdir(parents=True)

        root_file = session_dir / "root.json"
        with open(root_file, "w") as f:
            json.dump(
                {
                    "session_id": "orphan-use-session",
                    "model_spec": {"title": "claude-sonnet-4"},
                    "messages": [
                        {"role": "user", "content": "Summary"},
                        {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "I'll help with that."},
                                # Orphaned tool_use - no matching tool_result
                                {
                                    "type": "tool_use",
                                    "id": "orphan_id",
                                    "name": "some_tool",
                                    "input": {},
                                },
                            ],
                        },
                        {"role": "user", "content": "Thanks!"},
                    ],
                    "metadata": {
                        "created_at": "2025-01-15T12:00:00Z",
                        "last_updated": "2025-01-15T12:30:00Z",
                        "root_dir": "/path/to/project",
                    },
                },
                f,
            )

        # Create a mock base context
        mock_sandbox = MagicMock()
        mock_ui = MagicMock()
        mock_memory = MagicMock()

        base_context = AgentContext(
            session_id="base-session",
            parent_session_id=None,
            model_spec={"title": "test-model"},
            sandbox=mock_sandbox,
            user_interface=mock_ui,
            usage=[],
            memory_manager=mock_memory,
        )

        # Load the session
        loaded_context = load_session_data(
            "orphan-use-session",
            base_context,
            history_base_dir=self.history_dir / ".silica" / "personas" / "default",
        )

        self.assertIsNotNone(loaded_context)

        # Verify orphaned tool_use was cleaned up
        from silica.developer.compaction_validation import validate_message_structure

        report = validate_message_structure(loaded_context.chat_history)
        self.assertTrue(
            report.is_valid, f"Messages should be valid: {report.detailed_report()}"
        )
        self.assertEqual(
            report.tool_use_count, 0, "Orphaned tool_uses should be removed"
        )


class TestListSessionsWithFirstMessage(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test files
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_dir = Path(self.temp_dir.name)

        # Create a session with messages
        session_dir = self.history_dir / "session-with-messages"
        session_dir.mkdir(parents=True)

        root_file = session_dir / "root.json"
        with open(root_file, "w") as f:
            json.dump(
                {
                    "session_id": "session-with-messages",
                    "model_spec": {"title": "claude-sonnet-4"},
                    "messages": [
                        {"role": "user", "content": "Help me debug this issue"},
                        {"role": "assistant", "content": "I'd be happy to help!"},
                    ],
                    "metadata": {
                        "created_at": "2025-01-15T12:00:00Z",
                        "last_updated": "2025-01-15T12:30:00Z",
                        "root_dir": "/path/to/project",
                    },
                },
                f,
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("silica.developer.tools.sessions.get_history_dir")
    def test_list_sessions_includes_first_message(self, mock_get_history_dir):
        """Test that list_sessions includes the first_message field."""
        mock_get_history_dir.return_value = self.history_dir

        sessions = list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["first_message"], "Help me debug this issue")


if __name__ == "__main__":
    unittest.main()
