#!/usr/bin/env python3
"""
Test for the compaction timing fix to ensure compaction happens before API calls,
not just at the beginning of the main loop.
"""

import unittest
from unittest import mock
import tempfile
import shutil

from silica.developer.context import AgentContext
from silica.developer.compacter import ConversationCompacter
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.memory import MemoryManager

# Import shared test fixtures
from tests.developer.conftest import MockAnthropicClient, MockUserInterface


class TestCompactionTimingFix(unittest.TestCase):
    """Tests for the compaction timing fix."""

    def setUp(self):
        """Set up test environment."""
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp()

        # Create sample messages - enough to potentially trigger compaction
        self.sample_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there! How can I help you today?"},
            {"role": "user", "content": "Tell me about conversation compaction"},
            {
                "role": "assistant",
                "content": "Conversation compaction is a technique used to manage long conversations...",
            },
            {"role": "user", "content": "Can you give me more details?"},
            {
                "role": "assistant",
                "content": "Sure! Here are the details about how compaction works in practice...",
            },
        ]

        # Create a mock client
        self.mock_client = MockAnthropicClient()

        # Create a model spec with small context window for testing
        self.model_spec = {
            "title": "claude-test-model",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 1000,  # Small context window to trigger compaction easily
        }

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    @mock.patch("anthropic.Client")
    def test_compaction_check_function(self, mock_client_class):
        """Test that check_and_apply_compaction method works correctly."""
        # Setup mock with compaction response
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

        # Create agent context
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-session",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
        )
        context._chat_history = self.sample_messages.copy()

        # Create mock metadata
        from silica.developer.compacter import CompactionMetadata

        metadata = CompactionMetadata(
            archive_name="pre-compaction-test.json",
            original_message_count=len(self.sample_messages),
            compacted_message_count=1,
            original_token_count=5000,
            summary_token_count=500,
            compaction_ratio=0.1,
        )

        # Mock the compact_conversation method to return metadata
        with mock.patch.object(
            ConversationCompacter, "compact_conversation", return_value=metadata
        ):
            # Create real compacter instance with mock client and test the method
            compacter = ConversationCompacter(client=mock_client)
            updated_context, compaction_applied = compacter.check_and_apply_compaction(
                context, self.model_spec["title"], ui, enable_compaction=True
            )

            # Verify compaction was applied
            self.assertTrue(compaction_applied)
            # Session ID should remain the same after compaction
            self.assertEqual(updated_context.session_id, "test-session")
            # Parent session ID should still be None for root contexts
            self.assertIsNone(updated_context.parent_session_id)
            self.assertIn("[bold green]✓ Compacted:", ui.system_messages[-1])

    @mock.patch("anthropic.Client")
    def test_no_compaction_when_disabled(self, mock_client_class):
        """Test that compaction doesn't happen when disabled."""
        # Setup mock
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

        # Create agent context
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-session",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
        )
        context._chat_history = self.sample_messages.copy()

        # Test with compaction disabled - use model title string, not dict
        compacter = ConversationCompacter(client=mock_client)
        updated_context, compaction_applied = compacter.check_and_apply_compaction(
            context, self.model_spec["title"], ui, enable_compaction=False
        )

        # Verify no compaction occurred
        self.assertFalse(compaction_applied)
        self.assertEqual(updated_context.session_id, "test-session")
        self.assertEqual(len(ui.system_messages), 0)

    @mock.patch("anthropic.Client")
    def test_no_compaction_with_pending_tools(self, mock_client_class):
        """Test that compaction doesn't happen when there are pending tool results."""
        # Setup mock
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

        # Create agent context
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-session",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
        )
        context._chat_history = self.sample_messages.copy()
        # Add pending tool results
        context.tool_result_buffer.append({"type": "text", "text": "Pending result"})

        # Test with pending tool results - use model title string, not dict
        compacter = ConversationCompacter(client=mock_client)
        updated_context, compaction_applied = compacter.check_and_apply_compaction(
            context, self.model_spec["title"], ui, enable_compaction=True
        )

        # Verify no compaction occurred due to pending tools
        self.assertFalse(compaction_applied)
        self.assertEqual(updated_context.session_id, "test-session")
        self.assertEqual(len(ui.system_messages), 0)


if __name__ == "__main__":
    unittest.main()
