#!/usr/bin/env python3
"""
Tests for AgentContext.rotate() method.
"""

import unittest
import tempfile
import shutil
import json
from pathlib import Path

from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.user_interface import UserInterface
from silica.developer.memory import MemoryManager


class MockUserInterface(UserInterface):
    """Mock for the user interface."""

    def __init__(self):
        self.system_messages = []

    def handle_system_message(self, message, markdown=True):
        """Record system messages."""
        self.system_messages.append(message)

    def permission_callback(self, action, resource, sandbox_mode, action_arguments):
        """Always allow."""
        return True

    def permission_rendering_callback(self, action, resource, action_arguments):
        """Do nothing."""

    def bare(self, message):
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
    ):
        """Do nothing."""

    def display_welcome_message(self):
        """Do nothing."""

    def get_user_input(self, prompt=""):
        """Return empty string."""
        return ""

    def handle_assistant_message(self, message, markdown=True):
        """Do nothing."""

    def handle_tool_result(self, name, result, markdown=True):
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


class TestAgentContextRotate(unittest.TestCase):
    """Tests for AgentContext.rotate() method."""

    def setUp(self):
        """Set up test environment."""
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp()

        # Create sample messages
        self.sample_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm doing well, thank you!"},
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

    def test_rotate_archives_root_json(self):
        """Test that rotate() archives the current root.json and returns new context."""
        # Create agent context with history_base_dir parameter
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-rotate-session",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".hdev",
        )
        context._chat_history = self.sample_messages.copy()

        # First, flush to create the root.json
        context.flush(context.chat_history, compact=False)

        # Verify root.json was created
        history_dir = Path(self.test_dir) / ".hdev" / "history" / "test-rotate-session"
        root_file = history_dir / "root.json"
        self.assertTrue(root_file.exists())

        # Read the original root.json
        with open(root_file, "r") as f:
            original_data = json.load(f)
        self.assertEqual(len(original_data["messages"]), 4)

        # Define new messages for the rotated context
        new_messages = [
            {"role": "user", "content": "This is a new conversation"},
            {"role": "assistant", "content": "Yes, this is rotated!"},
        ]

        # Now rotate with a custom suffix and new messages (mutates context in place)
        # No metadata provided in this test
        archive_name = context.rotate(
            "archive-test-20250112_140530", new_messages, None
        )

        # Verify the archive was created with the correct name
        expected_archive = "archive-test-20250112_140530.json"
        self.assertEqual(archive_name, expected_archive)

        archive_file = history_dir / expected_archive
        self.assertTrue(
            archive_file.exists(), f"Archive file not found: {archive_file}"
        )

        # Read the archive and verify it contains the original conversation
        with open(archive_file, "r") as f:
            archived_data = json.load(f)
        self.assertEqual(len(archived_data["messages"]), 4)
        self.assertEqual(archived_data["messages"], self.sample_messages)

        # Verify root.json still exists (rotate doesn't delete it)
        self.assertTrue(root_file.exists())

        # Verify context was mutated in place to have the new messages
        self.assertEqual(len(context.chat_history), 2)
        self.assertEqual(context.chat_history, new_messages)

        # Verify tool buffer was cleared
        self.assertEqual(len(context.tool_result_buffer), 0)

    def test_rotate_on_sub_agent_raises_error(self):
        """Test that rotate() raises ValueError on sub-agent contexts."""
        # Create a sub-agent context (with parent_session_id)
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id="parent-session-123",  # This makes it a sub-agent
            session_id="sub-agent-session",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".hdev",
        )

        # Attempting to rotate should raise ValueError
        with self.assertRaises(ValueError) as cm:
            context.rotate("test-archive", [], None)

        self.assertIn("root contexts", str(cm.exception))
        self.assertIn("sub-agent", str(cm.exception))

    def test_rotate_multiple_times(self):
        """Test that rotate() can be called multiple times with different archives."""
        # Create agent context with history_base_dir parameter
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-multi-rotate",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".hdev",
        )
        context._chat_history = self.sample_messages.copy()

        # First flush
        context.flush(context.chat_history, compact=False)

        history_dir = Path(self.test_dir) / ".hdev" / "history" / "test-multi-rotate"
        root_file = history_dir / "root.json"

        # First rotation (mutates context in place)
        new_messages1 = [{"role": "user", "content": "Rotated 1"}]
        archive1 = context.rotate("first-archive-20250112_140000", new_messages1, None)
        archive1_file = history_dir / archive1
        self.assertTrue(archive1_file.exists())

        # Modify the conversation (add a message to the context)
        context._chat_history.append({"role": "user", "content": "New message"})
        context.flush(context.chat_history, compact=False)

        # Second rotation (mutates context in place again)
        new_messages2 = [{"role": "user", "content": "Rotated 2"}]
        archive2 = context.rotate("second-archive-20250112_150000", new_messages2, None)
        archive2_file = history_dir / archive2
        self.assertTrue(archive2_file.exists())

        # Both archives should exist
        self.assertTrue(archive1_file.exists())
        self.assertTrue(archive2_file.exists())
        self.assertTrue(root_file.exists())

        # Verify first archive has 4 messages
        with open(archive1_file, "r") as f:
            archive1_data = json.load(f)
        self.assertEqual(len(archive1_data["messages"]), 4)

        # Verify second archive has 2 messages (from the rotated context)
        with open(archive2_file, "r") as f:
            archive2_data = json.load(f)
        self.assertEqual(len(archive2_data["messages"]), 2)

    def test_rotate_when_root_json_missing(self):
        """Test that rotate() handles the case when root.json doesn't exist yet."""
        # Create agent context with history_base_dir parameter
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-no-root",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".hdev",
        )

        # Try to rotate when root.json doesn't exist yet
        # Should return the archive name and mutate context, but not create the archive file
        new_messages = [{"role": "user", "content": "New conversation"}]
        archive_name = context.rotate(
            "test-archive-20250112_140530", new_messages, None
        )

        self.assertEqual(archive_name, "test-archive-20250112_140530.json")

        # Verify no archive was created (since there was nothing to archive)
        history_dir = Path(self.test_dir) / ".hdev" / "history" / "test-no-root"
        if history_dir.exists():
            archive_file = history_dir / archive_name
            self.assertFalse(archive_file.exists())

        # Verify context was mutated to have the new messages
        self.assertEqual(context.chat_history, new_messages)

    def test_rotate_stores_metadata(self):
        """Test that rotate() stores compaction metadata when provided."""
        # Create agent context with history_base_dir parameter
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-metadata-storage",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".hdev",
        )
        context._chat_history = self.sample_messages.copy()

        # First, flush to create the root.json
        context.flush(context.chat_history, compact=False)

        # Create sample metadata
        from silica.developer.compacter import CompactionMetadata

        metadata = CompactionMetadata(
            archive_name="test-archive.json",
            original_message_count=4,
            compacted_message_count=2,
            original_token_count=1000,
            summary_token_count=200,
            compaction_ratio=0.2,
        )

        # Rotate with metadata
        new_messages = [
            {"role": "user", "content": "Summary message"},
        ]
        context.rotate("test-archive", new_messages, metadata)

        # Verify metadata was stored in the context
        self.assertTrue(hasattr(context, "_compaction_metadata"))
        self.assertEqual(context._compaction_metadata, metadata)

        # Flush the context - this should include the metadata in root.json
        context.flush(context.chat_history, compact=False)

        # Read the root.json and verify metadata is present
        history_dir = (
            Path(self.test_dir) / ".hdev" / "history" / "test-metadata-storage"
        )
        root_file = history_dir / "root.json"

        with open(root_file, "r") as f:
            root_data = json.load(f)

        self.assertIn("compaction", root_data)
        self.assertEqual(root_data["compaction"]["is_compacted"], True)
        self.assertEqual(root_data["compaction"]["original_message_count"], 4)
        self.assertEqual(root_data["compaction"]["compacted_message_count"], 2)
        self.assertEqual(root_data["compaction"]["original_token_count"], 1000)
        self.assertEqual(root_data["compaction"]["summary_token_count"], 200)
        self.assertEqual(root_data["compaction"]["compaction_ratio"], 0.2)

        # Verify metadata was cleared after flush
        self.assertFalse(hasattr(context, "_compaction_metadata"))


if __name__ == "__main__":
    unittest.main()
