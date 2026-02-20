#!/usr/bin/env python3
"""
Tests for AgentContext.rotate() method.
"""

import unittest
import tempfile
import shutil
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

    def permission_callback(
        self, action, resource, sandbox_mode, action_arguments, group=None
    ):
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
            "title": "claude-opus-4-6",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 200000,
        }

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    def test_rotate_archives_context(self):
        """Test that rotate() archives the current context and returns new context."""
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
            history_base_dir=Path(self.test_dir) / ".silica" / "personas" / "default",
        )
        context._chat_history = self.sample_messages.copy()

        # First, flush to create v2 files
        context.flush(context.chat_history, compact=False)

        history_dir = (
            Path(self.test_dir)
            / ".silica"
            / "personas"
            / "default"
            / "history"
            / "test-rotate-session"
        )
        # v2 files should exist
        self.assertTrue((history_dir / "session.json").exists())
        self.assertTrue((history_dir / "root.context.jsonl").exists())

        # Read context before rotation
        from silica.developer.session_store import SessionStore

        store = SessionStore(history_dir)
        ctx_before = store.read_context()
        self.assertEqual(len(ctx_before), 4)

        # Define new messages for the rotated context
        new_messages = [
            {"role": "user", "content": "This is a new conversation"},
            {"role": "assistant", "content": "Yes, this is rotated!"},
        ]

        # Now rotate with a custom suffix and new messages
        archive_name = context.rotate(
            "archive-test-20250112_140530", new_messages, None
        )

        # Verify the archive was created with the correct name (v2 format)
        expected_archive = "archive-test-20250112_140530.context.jsonl"
        self.assertEqual(archive_name, expected_archive)

        # Context archive should exist
        archive_ctx = history_dir / expected_archive
        self.assertTrue(archive_ctx.exists(), f"Archive file not found: {archive_ctx}")

        # Verify context was mutated in place to have the new messages
        self.assertEqual(len(context.chat_history), 2)
        self.assertEqual(context.chat_history, new_messages)

        # Verify tool buffer was cleared
        self.assertEqual(len(context.tool_result_buffer), 0)

        # Verify current context.jsonl has the new messages
        store2 = SessionStore(history_dir)
        ctx_after = store2.read_context()
        self.assertEqual(len(ctx_after), 2)
        self.assertEqual(ctx_after[0]["content"], "This is a new conversation")

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
            history_base_dir=Path(self.test_dir) / ".silica" / "personas" / "default",
        )

        # Attempting to rotate should raise ValueError
        with self.assertRaises(ValueError) as cm:
            context.rotate("test-archive", [], None)

        self.assertIn("root contexts", str(cm.exception))
        self.assertIn("sub-agent", str(cm.exception))

    def test_rotate_multiple_times(self):
        """Test that rotate() can be called multiple times with different archives."""
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
            history_base_dir=Path(self.test_dir) / ".silica" / "personas" / "default",
        )
        context._chat_history = self.sample_messages.copy()

        # First flush
        context.flush(context.chat_history, compact=False)

        history_dir = (
            Path(self.test_dir)
            / ".silica"
            / "personas"
            / "default"
            / "history"
            / "test-multi-rotate"
        )

        # First rotation
        new_messages1 = [{"role": "user", "content": "Rotated 1"}]
        archive1 = context.rotate("first-archive-20250112_140000", new_messages1, None)
        archive1_ctx = history_dir / archive1
        self.assertTrue(archive1_ctx.exists())

        # Modify the conversation (add a message to the context)
        context._chat_history.append({"role": "user", "content": "New message"})
        context.flush(context.chat_history, compact=False)

        # Second rotation
        new_messages2 = [{"role": "user", "content": "Rotated 2"}]
        archive2 = context.rotate("second-archive-20250112_150000", new_messages2, None)
        archive2_ctx = history_dir / archive2
        self.assertTrue(archive2_ctx.exists())

        # Both archives should exist
        self.assertTrue(archive1_ctx.exists())
        self.assertTrue(archive2_ctx.exists())

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
            history_base_dir=Path(self.test_dir) / ".silica" / "personas" / "default",
        )

        # Try to rotate when root.json doesn't exist yet
        # Should return the archive name and mutate context, but not create the archive file
        new_messages = [{"role": "user", "content": "New conversation"}]
        archive_name = context.rotate(
            "test-archive-20250112_140530", new_messages, None
        )

        self.assertEqual(archive_name, "test-archive-20250112_140530.context.jsonl")

        # Verify no context.jsonl archive was created (since there was no prior context)
        history_dir = (
            Path(self.test_dir)
            / ".silica"
            / "personas"
            / "default"
            / "history"
            / "test-no-root"
        )
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
            history_base_dir=Path(self.test_dir) / ".silica" / "personas" / "default",
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

        # Flush the context - this should include the metadata in session.json
        context.flush(context.chat_history, compact=False)

        # Read session.json and verify metadata is present
        history_dir = (
            Path(self.test_dir)
            / ".silica"
            / "personas"
            / "default"
            / "history"
            / "test-metadata-storage"
        )
        from silica.developer.session_store import SessionStore

        store = SessionStore(history_dir)
        session_meta = store.read_session_meta()

        self.assertIn("compaction", session_meta)
        self.assertEqual(session_meta["compaction"]["is_compacted"], True)
        self.assertEqual(session_meta["compaction"]["original_message_count"], 4)
        self.assertEqual(session_meta["compaction"]["compacted_message_count"], 2)
        self.assertEqual(session_meta["compaction"]["original_token_count"], 1000)
        self.assertEqual(session_meta["compaction"]["summary_token_count"], 200)
        self.assertEqual(session_meta["compaction"]["compaction_ratio"], 0.2)

        # Verify metadata was cleared after flush
        self.assertFalse(hasattr(context, "_compaction_metadata"))


class TestAgentContextCompactInPlace(unittest.TestCase):
    """Tests for AgentContext.compact_in_place() method."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.sample_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm doing well, thank you!"},
        ]
        self.model_spec = {
            "title": "claude-opus-4-6",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 200000,
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _make_context(self, parent_session_id=None, session_id="test-compact"):
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        return AgentContext(
            parent_session_id=parent_session_id,
            session_id=session_id,
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".silica" / "personas" / "default",
        )

    def test_compact_in_place_replaces_history(self):
        """compact_in_place should replace chat history with new messages."""
        context = self._make_context()
        context._chat_history = self.sample_messages.copy()

        new_messages = [
            {"role": "user", "content": "Compacted summary"},
            {"role": "assistant", "content": "Continuing..."},
        ]
        context.compact_in_place(new_messages)

        self.assertEqual(context.chat_history, new_messages)

    def test_compact_in_place_clears_tool_buffer(self):
        """compact_in_place should clear the tool result buffer."""
        context = self._make_context()
        context._chat_history = self.sample_messages.copy()
        context._tool_result_buffer = [{"type": "tool_result", "content": "something"}]

        context.compact_in_place([{"role": "user", "content": "Summary"}])

        self.assertEqual(len(context.tool_result_buffer), 0)

    def test_compact_in_place_stores_metadata(self):
        """compact_in_place should store compaction metadata."""
        from silica.developer.compacter import CompactionMetadata

        context = self._make_context()
        context._chat_history = self.sample_messages.copy()

        metadata = CompactionMetadata(
            archive_name="n/a",
            original_message_count=4,
            compacted_message_count=1,
            original_token_count=500,
            summary_token_count=100,
            compaction_ratio=0.2,
        )

        context.compact_in_place(
            [{"role": "user", "content": "Summary"}],
            compaction_metadata=metadata,
        )

        self.assertEqual(context._compaction_metadata, metadata)

    def test_compact_in_place_works_on_sub_agent(self):
        """compact_in_place should work on sub-agent contexts (unlike rotate)."""
        context = self._make_context(
            parent_session_id="parent-123",
            session_id="sub-agent-456",
        )
        context._chat_history = self.sample_messages.copy()

        new_messages = [
            {"role": "user", "content": "Compacted sub-agent history"},
        ]
        # Should NOT raise ValueError
        context.compact_in_place(new_messages)

        self.assertEqual(context.chat_history, new_messages)
        self.assertEqual(len(context.tool_result_buffer), 0)

    def test_compact_in_place_works_on_root_context(self):
        """compact_in_place should also work on root contexts."""
        context = self._make_context(parent_session_id=None)
        context._chat_history = self.sample_messages.copy()

        new_messages = [{"role": "user", "content": "Compacted root history"}]
        context.compact_in_place(new_messages)

        self.assertEqual(context.chat_history, new_messages)

    def test_compact_in_place_does_not_create_archive(self):
        """compact_in_place should NOT create any pre-compaction archive files."""
        context = self._make_context(
            parent_session_id="parent-123",
            session_id="sub-agent-789",
        )
        context._chat_history = self.sample_messages.copy()
        context.flush(context.chat_history, compact=False)

        # Get the history dir for this sub-agent (inside parent's dir)
        history_dir = (
            Path(self.test_dir)
            / ".silica"
            / "personas"
            / "default"
            / "history"
            / "parent-123"
        )

        context.compact_in_place([{"role": "user", "content": "Compacted"}])

        # Verify no pre-compaction archive files were created
        archive_files = [f for f in history_dir.iterdir() if "pre-compaction" in f.name]
        self.assertEqual(len(archive_files), 0)

    def test_compact_in_place_flushes_to_disk(self):
        """compact_in_place should persist the compacted state."""
        context = self._make_context(
            parent_session_id="parent-123",
            session_id="sub-agent-flush-test",
        )
        context._chat_history = self.sample_messages.copy()

        new_messages = [{"role": "user", "content": "Compacted"}]
        context.compact_in_place(new_messages)

        # Read back the persisted v2 files
        history_dir = (
            Path(self.test_dir)
            / ".silica"
            / "personas"
            / "default"
            / "history"
            / "parent-123"
        )
        from silica.developer.session_store import SessionStore

        store = SessionStore(history_dir, agent_name="sub-agent-flush-test")
        ctx_msgs = store.read_context()
        self.assertEqual(len(ctx_msgs), 1)
        self.assertEqual(ctx_msgs[0]["content"], "Compacted")


if __name__ == "__main__":
    unittest.main()
