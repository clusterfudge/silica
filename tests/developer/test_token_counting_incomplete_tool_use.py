#!/usr/bin/env python3
"""
Test for token counting with incomplete tool_use states.
"""

import unittest
import tempfile
from unittest.mock import Mock

from silica.developer.compacter import ConversationCompacter
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


class TestTokenCountingIncompleteToolUse(unittest.TestCase):
    """Tests for token counting with incomplete tool_use states."""

    def setUp(self):
        """Set up test environment."""
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp()

        # Create a model spec
        self.model_spec = {
            "title": "claude-3-5-sonnet-latest",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 200000,
        }

    def test_has_incomplete_tool_use_detection(self):
        """Test detection of incomplete tool_use states."""
        # Create a mock client for testing
        mock_client = Mock()
        compacter = ConversationCompacter(client=mock_client)

        # Test messages with incomplete tool_use
        incomplete_messages = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll help you."},
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "test_tool",
                        "input": {},
                    },
                ],
            },
        ]

        # Test messages with complete tool_use/tool_result
        complete_messages = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll help you."},
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "test_tool",
                        "input": {},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "Tool result",
                    }
                ],
            },
        ]

        # Test messages with no tool_use
        no_tool_messages = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi there!"}],
            },
        ]

        # Assertions
        self.assertTrue(compacter._has_incomplete_tool_use(incomplete_messages))
        self.assertFalse(compacter._has_incomplete_tool_use(complete_messages))
        self.assertFalse(compacter._has_incomplete_tool_use(no_tool_messages))
        self.assertFalse(compacter._has_incomplete_tool_use([]))

    def test_token_counting_with_incomplete_tool_use(self):
        """Test that token counting works with incomplete tool_use using estimation."""
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

        # Set up chat history with incomplete tool_use
        context._chat_history = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll help you."},
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "test_tool",
                        "input": {},
                    },
                ],
            },
        ]

        # Create a mock client for testing
        mock_client = Mock()
        compacter = ConversationCompacter(client=mock_client)

        # This should not raise an error and should return an estimated token count
        token_count = compacter.count_tokens(context, "claude-3-5-sonnet-latest")

        # Token count should be positive (estimated)
        self.assertGreater(token_count, 0)
        self.assertIsInstance(token_count, int)

    def test_agent_token_counting_skip_for_incomplete(self):
        """Test that agent skips token counting when chat_history has incomplete tool_use."""
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

        # Set up chat history with incomplete tool_use
        context._chat_history = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll help you."},
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "test_tool",
                        "input": {},
                    },
                ],
            },
        ]
        context._tool_result_buffer = []

        # Simulate the agent logic for token counting
        enable_compaction = True
        conversation_size_for_display = None
        context_window_for_display = None

        if enable_compaction and not context.tool_result_buffer:
            # Create a mock client for testing
            mock_client = Mock()
            compacter = ConversationCompacter(client=mock_client)
            model_name = self.model_spec["title"]

            # Check if conversation has incomplete tool_use before counting tokens
            if compacter._has_incomplete_tool_use(context.chat_history):
                # Skip token counting for incomplete states
                pass
            else:
                # Get context window size for this model
                context_window_for_display = compacter.model_context_windows.get(
                    model_name, 100000
                )

                # Count tokens for complete conversation
                conversation_size_for_display = compacter.count_tokens(
                    context, model_name
                )

            # Store for later display
            context._last_conversation_size = conversation_size_for_display
            context._last_context_window = context_window_for_display

        # Should have skipped token counting
        self.assertIsNone(context._last_conversation_size)
        self.assertIsNone(context._last_context_window)


if __name__ == "__main__":
    unittest.main()
