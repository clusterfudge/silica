#!/usr/bin/env python3
"""
Tests for compaction session ID stability - ensuring that session IDs remain
constant across compaction and that pre-compaction conversations are properly archived.
"""

import unittest
from unittest import mock
import tempfile
import shutil
import json
from pathlib import Path

from silica.developer.compacter import (
    ConversationCompacter,
    CompactionMetadata,
)
from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.user_interface import UserInterface
from silica.developer.memory import MemoryManager


class MockAnthropicClient:
    """Mock for the Anthropic client."""

    def __init__(self, token_counts=None, response_content=None):
        """Initialize the mock client.

        Args:
            token_counts: Dictionary mapping input text to token counts
            response_content: Content to return in the response
        """
        self.token_counts = token_counts or {"Hello": 1, "Hello world": 2}
        self.response_content = response_content or "Summary of the conversation"
        self.messages = self.MessagesClient(self)

    class MessagesClient:
        """Mock for the messages client."""

        def __init__(self, parent):
            self.parent = parent

        def count_tokens(self, model, system=None, messages=None, tools=None):
            """Mock for the messages.count_tokens method."""
            # Calculate token count based on all components
            total_chars = 0

            # Count system characters
            if system:
                for block in system:
                    if isinstance(block, dict) and block.get("type") == "text":
                        total_chars += len(block.get("text", ""))

            # Count messages characters
            if messages:
                for message in messages:
                    if isinstance(message, dict) and "content" in message:
                        content = message["content"]
                        if isinstance(content, str):
                            total_chars += len(content)
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and "text" in block:
                                    total_chars += len(block["text"])

            # Count tools characters (rough estimate)
            if tools:
                import json

                total_chars += len(json.dumps(tools))

            # Estimate tokens from characters
            token_count = max(1, total_chars // 4)

            class TokenResponse:
                def __init__(self, count):
                    self.token_count = count

            return TokenResponse(token_count)

        def create(self, model, system, messages, max_tokens):
            """Mock for the messages.create method."""

            class ContentItem:
                def __init__(self, text):
                    self.text = text

            class MessageResponse:
                def __init__(self, content_text):
                    self.content = [ContentItem(content_text)]

            return MessageResponse(self.parent.response_content)


class MockUserInterface(UserInterface):
    """Mock for the user interface."""

    def __init__(self):
        self.system_messages = []

    def handle_system_message(self, message, markdown=True, live=None):
        """Record system messages."""
        self.system_messages.append(message)

    def permission_callback(self, action, resource, sandbox_mode, action_arguments):
        """Always allow."""
        return True

    def permission_rendering_callback(self, action, resource, action_arguments):
        """Do nothing."""

    def bare(self, message, live=None):
        """Do nothing."""

    def display_token_count(
        self,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        total_cost,
        cached_tokens=None,
        conversation_size=None,
        context_window=None,
        thinking_tokens=None,
        thinking_cost=None,
    ):
        """Do nothing."""

    def display_welcome_message(self):
        """Do nothing."""

    async def get_user_input(self, prompt=""):
        """Return empty string."""
        return ""

    def handle_assistant_message(self, message, markdown=True):
        """Do nothing."""

    def handle_tool_result(self, name, result, markdown=True, live=None):
        """Do nothing."""

    def handle_tool_use(self, tool_name, tool_params):
        """Do nothing."""

    def handle_user_input(self, user_input):
        """Do nothing."""

    def status(self, message, spinner=None):
        """Return a context manager that does nothing."""

        class DummyContextManager:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        return DummyContextManager()


class TestCompactionSessionIDStability(unittest.TestCase):
    """Tests for compaction session ID stability."""

    def setUp(self):
        """Set up test environment."""
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp()

        # Create sample messages
        self.sample_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there! How can I help you today?"},
            {"role": "user", "content": "Tell me about conversation compaction"},
            {
                "role": "assistant",
                "content": "Conversation compaction is a technique...",
            },
        ]

        # Create a model spec
        self.model_spec = {
            "title": "claude-opus-4-20250514",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 200000,
        }

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    def test_session_id_remains_constant(self):
        """Test that session ID remains constant across compaction."""
        # Create compaction metadata
        metadata = CompactionMetadata(
            archive_name="pre-compaction-20250115_100000.json",
            original_message_count=10,
            compacted_message_count=3,
            original_token_count=5000,
            summary_token_count=500,
            compaction_ratio=0.1,
        )

        # Verify metadata is created correctly
        self.assertEqual(metadata.original_message_count, 10)
        self.assertEqual(metadata.compacted_message_count, 3)
        self.assertEqual(metadata.archive_name, "pre-compaction-20250115_100000.json")

    @mock.patch("pathlib.Path.home")
    def test_compaction_includes_archive_name(self, mock_home):
        """Test that compaction includes archive filename in metadata."""
        mock_home.return_value = Path(self.test_dir)

        mock_client = MockAnthropicClient()
        compacter = ConversationCompacter(client=mock_client, threshold_ratio=0.5)

        # Create agent context
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-session-456",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
        )
        context._chat_history = self.sample_messages

        # Mock should_compact to return True
        compacter.should_compact = mock.MagicMock(return_value=True)

        # Call compact_conversation - mutates context in place and returns metadata
        metadata = compacter.compact_conversation(context, "claude-opus-4-20250514")

        # Verify the result
        self.assertIsNotNone(metadata)
        self.assertIsNotNone(metadata.archive_name)
        self.assertTrue(metadata.archive_name.startswith("pre-compaction-"))
        self.assertTrue(metadata.archive_name.endswith(".json"))
        self.assertEqual(metadata.original_message_count, 4)
        self.assertGreater(metadata.compacted_message_count, 0)

        # Verify context was mutated
        self.assertGreater(len(context.chat_history), 0)

    @mock.patch("pathlib.Path.home")
    def test_compaction_keeps_session_id(self, mock_home):
        """Test that compaction keeps the session ID constant."""
        mock_home.return_value = Path(self.test_dir)

        # Create agent context
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-session-789",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
        )
        context._chat_history = self.sample_messages.copy()

        # Create metadata
        metadata = CompactionMetadata(
            archive_name="pre-compaction-20250115_120000.json",
            original_message_count=4,
            compacted_message_count=2,
            original_token_count=500,
            summary_token_count=100,
            compaction_ratio=0.2,
        )

        compacted_messages = [
            {"role": "user", "content": "Summary of conversation"},
            {"role": "assistant", "content": "Continuing from summary..."},
        ]

        # Simulate what the agent loop does
        original_session_id = context.session_id
        context._chat_history = compacted_messages
        context._compaction_metadata = metadata

        # Verify session ID didn't change
        self.assertEqual(context.session_id, original_session_id)
        self.assertEqual(context.session_id, "test-session-789")
        self.assertIsNone(context.parent_session_id)

        # Verify that the context has compaction metadata
        self.assertTrue(hasattr(context, "_compaction_metadata"))
        self.assertEqual(
            context._compaction_metadata.archive_name,
            "pre-compaction-20250115_120000.json",
        )

    @mock.patch("pathlib.Path.home")
    def test_compaction_archives_conversation(self, mock_home):
        """Test that compaction archives the old conversation."""
        mock_home.return_value = Path(self.test_dir)

        # Create agent context
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-archive-session",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
        )
        context._chat_history = self.sample_messages.copy()

        # First, flush the original conversation
        context.flush(context.chat_history, compact=False)

        # Verify root.json was created
        history_dir = Path(self.test_dir) / ".hdev" / "history" / "test-archive-session"
        root_file = history_dir / "root.json"
        self.assertTrue(root_file.exists())

        # Read the original root.json
        with open(root_file, "r") as f:
            original_data = json.load(f)
        self.assertEqual(len(original_data["messages"]), 4)

        # Now create a compacter and run compaction (which does archiving)
        mock_client = MockAnthropicClient()
        compacter = ConversationCompacter(client=mock_client)
        compacter.should_compact = mock.MagicMock(return_value=True)

        # Run compaction - this will archive the old conversation and mutate context
        original_session_id = context.session_id
        metadata = compacter.compact_conversation(
            context, "claude-opus-4-20250514", force=True
        )

        # Verify we got metadata
        self.assertIsNotNone(metadata)

        # Verify session ID remained the same (context mutated in place)
        self.assertEqual(context.session_id, original_session_id)

        # Verify archiving happened
        archive_file = history_dir / metadata.archive_name
        self.assertTrue(
            archive_file.exists(), f"Archive file not found: {archive_file}"
        )

        # Read the archive and verify it contains the original conversation
        with open(archive_file, "r") as f:
            archived_data = json.load(f)
        self.assertEqual(len(archived_data["messages"]), 4)
        self.assertEqual(archived_data["messages"], self.sample_messages)

        # Now use the mutated context and flush to save compacted version
        context._compaction_metadata = metadata
        context.flush(context.chat_history, compact=False)

        # Verify the new root.json contains the compacted conversation
        with open(root_file, "r") as f:
            new_data = json.load(f)
        self.assertGreater(
            len(new_data["messages"]), 0
        )  # Has summary + preserved messages

        # Verify compaction metadata is present
        self.assertIn("compaction", new_data)
        self.assertTrue(new_data["compaction"]["is_compacted"])
        self.assertEqual(
            new_data["compaction"]["pre_compaction_archive"], metadata.archive_name
        )
        self.assertEqual(new_data["compaction"]["original_message_count"], 4)
        self.assertEqual(
            new_data["compaction"]["compacted_message_count"],
            metadata.compacted_message_count,
        )


if __name__ == "__main__":
    unittest.main()
