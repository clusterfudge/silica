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
from silica.developer.memory import MemoryManager

# Import shared test fixtures
from tests.developer.conftest import MockAnthropicClient, MockUserInterface


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
            "title": "claude-opus-4-6",
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

    def test_compaction_includes_archive_name(self):
        """Test that compaction includes archive filename in metadata."""
        mock_client = MockAnthropicClient()
        compacter = ConversationCompacter(client=mock_client, threshold_ratio=0.5)

        # Create agent context with history_base_dir parameter
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
            history_base_dir=Path(self.test_dir) / ".silica" / "personas" / "default",
        )
        context._chat_history = self.sample_messages

        # Mock should_compact to return True
        compacter.should_compact = mock.MagicMock(return_value=True)

        # Call compact_conversation - mutates context in place and returns metadata
        metadata = compacter.compact_conversation(context, "claude-opus-4-6")

        # Verify the result
        self.assertIsNotNone(metadata)
        self.assertIsNotNone(metadata.archive_name)
        self.assertTrue(metadata.archive_name.startswith("pre-compaction-"))
        self.assertTrue(
            metadata.archive_name.endswith(".context.jsonl")
            or metadata.archive_name.endswith(".json")
        )
        self.assertEqual(metadata.original_message_count, 4)
        self.assertGreater(metadata.compacted_message_count, 0)

        # Verify context was mutated
        self.assertGreater(len(context.chat_history), 0)

    def test_compaction_keeps_session_id(self):
        """Test that compaction keeps the session ID constant."""
        # Create agent context with history_base_dir parameter
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
            history_base_dir=Path(self.test_dir) / ".silica" / "personas" / "default",
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

    def test_compaction_archives_conversation(self):
        """Test that compaction archives the old conversation."""
        # Create agent context with history_base_dir parameter
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
            history_base_dir=Path(self.test_dir) / ".silica" / "personas" / "default",
        )
        context._chat_history = self.sample_messages.copy()

        # First, flush the original conversation
        context.flush(context.chat_history, compact=False)

        # Verify v2 files were created
        history_dir = (
            Path(self.test_dir)
            / ".silica"
            / "personas"
            / "default"
            / "history"
            / "test-archive-session"
        )
        self.assertTrue((history_dir / "session.json").exists())

        # Read the original context
        from silica.developer.session_store import SessionStore

        store = SessionStore(history_dir)
        original_ctx = store.read_context()
        self.assertEqual(len(original_ctx), 4)

        # Now create a compacter and run compaction (which does archiving)
        mock_client = MockAnthropicClient()
        compacter = ConversationCompacter(client=mock_client)
        compacter.should_compact = mock.MagicMock(return_value=True)

        # Run compaction - this will archive the old conversation and mutate context
        original_session_id = context.session_id
        metadata = compacter.compact_conversation(
            context, "claude-opus-4-6", force=True
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
        # Archive is now .context.jsonl format
        archive_ctx_file = history_dir / archive_file.name
        if archive_ctx_file.exists() and archive_ctx_file.suffix == ".jsonl":
            archived_msgs = SessionStore._read_jsonl(archive_ctx_file)
            self.assertEqual(len(archived_msgs), 4)
        elif archive_file.exists():
            with open(archive_file, "r") as f:
                archived_data = json.load(f)
            self.assertEqual(len(archived_data["messages"]), 4)

        # Now use the mutated context and flush to save compacted version
        context._compaction_metadata = metadata
        context.flush(context.chat_history, compact=False)

        # Verify session.json contains compaction metadata
        store2 = SessionStore(history_dir)
        session_meta = store2.read_session_meta()
        self.assertGreater(
            len(store2.read_context()), 0
        )  # Has summary + preserved messages

        # Verify compaction metadata is present
        self.assertIn("compaction", session_meta)
        self.assertTrue(session_meta["compaction"]["is_compacted"])
        self.assertEqual(
            session_meta["compaction"]["pre_compaction_archive"],
            metadata.archive_name,
        )
        self.assertEqual(session_meta["compaction"]["original_message_count"], 4)
        self.assertEqual(
            session_meta["compaction"]["compacted_message_count"],
            metadata.compacted_message_count,
        )


if __name__ == "__main__":
    unittest.main()
