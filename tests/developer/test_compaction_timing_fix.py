#!/usr/bin/env python3
"""
Test for the compaction timing fix to ensure compaction happens before API calls,
not just at the beginning of the main loop.
"""

import unittest
from unittest import mock
import tempfile
import shutil

from silica.developer.agent_loop import _check_and_apply_compaction
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
        self.count_tokens_called = False
        self.messages_create_called = False

        # Create a messages attribute for the new API style
        self.messages = self.MessagesClient(self)

    class MessagesClient:
        """Mock for the messages client."""

        def __init__(self, parent):
            self.parent = parent

        def count_tokens(self, model, system=None, messages=None, tools=None):
            """Mock for the messages.count_tokens method."""
            self.parent.count_tokens_called = True

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

            # Create a response object with a token_count attribute
            class TokenResponse:
                def __init__(self, count):
                    self.token_count = count

            return TokenResponse(token_count)

        def create(self, model, system, messages, max_tokens):
            """Mock for the messages.create method."""
            self.parent.messages_create_called = True

            # Create a response object with content
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
        """Test that the _check_and_apply_compaction function works correctly."""
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

        # Create a mock transition
        from silica.developer.compacter import (
            CompactionTransition,
            CompactionSummary,
        )

        summary = CompactionSummary(
            original_message_count=len(self.sample_messages),
            original_token_count=5000,
            summary_token_count=500,
            compaction_ratio=0.1,
            summary="Test summary",
        )

        transition = CompactionTransition(
            original_session_id="test-session",
            new_session_id="new-test-session",
            compacted_messages=[{"role": "user", "content": "Summary"}],
            summary=summary,
        )

        # Create a mock compacter instance that returns our transition
        mock_compacter_instance = mock.Mock()
        mock_compacter_instance.compact_and_transition.return_value = transition

        # Mock the compaction logic to always trigger
        with mock.patch(
            "silica.developer.compacter.ConversationCompacter",
            return_value=mock_compacter_instance,
        ):
            # Test the function
            updated_context, compaction_applied = _check_and_apply_compaction(
                context, self.model_spec, ui, enable_compaction=True
            )

            # Verify compaction was applied
            self.assertTrue(compaction_applied)
            self.assertEqual(updated_context.session_id, "new-test-session")
            self.assertEqual(updated_context.parent_session_id, "test-session")
            self.assertIn("[bold green]Conversation compacted:", ui.system_messages[-1])

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

        # Test with compaction disabled
        updated_context, compaction_applied = _check_and_apply_compaction(
            context, self.model_spec, ui, enable_compaction=False
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

        # Test with pending tool results
        updated_context, compaction_applied = _check_and_apply_compaction(
            context, self.model_spec, ui, enable_compaction=True
        )

        # Verify no compaction occurred due to pending tools
        self.assertFalse(compaction_applied)
        self.assertEqual(updated_context.session_id, "test-session")
        self.assertEqual(len(ui.system_messages), 0)


if __name__ == "__main__":
    unittest.main()
