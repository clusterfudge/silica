#!/usr/bin/env python3
"""
Tests for conversation compaction with Extended Thinking.
"""

import unittest
import tempfile
import shutil
from anthropic.types import TextBlock, ThinkingBlock

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


class TestCompactionWithThinking(unittest.TestCase):
    """Tests for compaction with thinking blocks."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()

        self.model_spec = {
            "title": "claude-sonnet-4-20250514",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 200000,
            "thinking_support": True,
            "thinking_pricing": 15.00,
        }

        # Create a minimal mock client for tests that don't need API calls
        class MinimalMockClient:
            def __init__(self):
                self.messages = None

        self.mock_client = MinimalMockClient()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    def test_has_thinking_detection_with_sdk_objects(self):
        """Test that _has_thinking_in_any_assistant_message detects SDK objects."""
        compacter = ConversationCompacter(client=self.mock_client)

        # Messages with SDK objects (as they appear in chat_history)
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {
                "role": "assistant",
                "content": [
                    ThinkingBlock(
                        signature="test_sig", thinking="Let me think", type="thinking"
                    ),
                    TextBlock(text="The answer is 4", type="text"),
                ],
            },
        ]

        result = compacter._has_thinking_in_any_assistant_message(messages)
        self.assertTrue(result, "Should detect thinking blocks in SDK objects")

    def test_has_thinking_detection_with_dicts(self):
        """Test that _has_thinking_in_any_assistant_message detects dict blocks."""
        compacter = ConversationCompacter(client=self.mock_client)

        # Messages with dicts (as they might appear after serialization)
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "Let me think",
                        "signature": "test_sig",
                    },
                    {"type": "text", "text": "The answer is 4"},
                ],
            },
        ]

        result = compacter._has_thinking_in_any_assistant_message(messages)
        self.assertTrue(result, "Should detect thinking blocks in dicts")

    def test_has_thinking_detected_in_middle_message(self):
        """Test that thinking blocks ARE detected even in middle messages.

        The API requires: if ANY message has thinking blocks, you MUST enable
        the thinking parameter. This test verifies we detect thinking even when
        it's not in the last message.
        """
        compacter = ConversationCompacter(client=self.mock_client)

        # Thinking in message 1, plain text in message 3 (last)
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "Let me think",
                        "signature": "test_sig",
                    },
                    {"type": "text", "text": "The answer is 4"},
                ],
            },
            {"role": "user", "content": "What is 3+3?"},
            {"role": "assistant", "content": [{"type": "text", "text": "Six"}]},
        ]

        result = compacter._has_thinking_in_any_assistant_message(messages)
        self.assertTrue(
            result, "Should detect thinking even when not in last assistant message"
        )

    def test_has_thinking_no_thinking_blocks(self):
        """Test that no thinking is detected when there are no thinking blocks."""
        compacter = ConversationCompacter(client=self.mock_client)

        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": [{"type": "text", "text": "Four"}]},
        ]

        result = compacter._has_thinking_in_any_assistant_message(messages)
        self.assertFalse(result, "Should not detect thinking when there are none")

    def test_count_tokens_with_thinking_enables_thinking_param(self):
        """Test that count_tokens enables thinking parameter when blocks are present."""

        # Create a mock client that tracks whether thinking was enabled
        class MockClient:
            def __init__(self):
                self.count_tokens_called = False
                self.thinking_enabled = False
                self.messages = self.MessagesClient(self)

            class MessagesClient:
                def __init__(self, parent):
                    self.parent = parent

                def count_tokens(
                    self, model, system=None, messages=None, tools=None, thinking=None
                ):
                    self.parent.count_tokens_called = True
                    if thinking is not None:
                        self.parent.thinking_enabled = True

                    class TokenResponse:
                        def __init__(self):
                            self.input_tokens = 100

                    return TokenResponse()

        mock_client = MockClient()
        compacter = ConversationCompacter(client=mock_client)

        # Create context with thinking blocks
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

        # Set chat history with thinking blocks
        context._chat_history = [
            {"role": "user", "content": "What is 2+2?"},
            {
                "role": "assistant",
                "content": [
                    ThinkingBlock(
                        signature="test_sig", thinking="Let me think", type="thinking"
                    ),
                    TextBlock(text="The answer is 4", type="text"),
                ],
            },
        ]

        # Count tokens
        compacter.count_tokens(context, "claude-sonnet-4-20250514")

        # Verify thinking was enabled
        self.assertTrue(
            mock_client.count_tokens_called, "count_tokens should be called"
        )
        self.assertTrue(
            mock_client.thinking_enabled,
            "thinking parameter should be enabled when thinking blocks are present",
        )

    def test_count_tokens_without_thinking_no_thinking_param(self):
        """Test that count_tokens doesn't enable thinking when no blocks present."""

        class MockClient:
            def __init__(self):
                self.thinking_enabled = False
                self.messages = self.MessagesClient(self)

            class MessagesClient:
                def __init__(self, parent):
                    self.parent = parent

                def count_tokens(
                    self, model, system=None, messages=None, tools=None, thinking=None
                ):
                    if thinking is not None:
                        self.parent.thinking_enabled = True

                    class TokenResponse:
                        def __init__(self):
                            self.input_tokens = 100

                    return TokenResponse()

        mock_client = MockClient()
        compacter = ConversationCompacter(client=mock_client)

        # Create context WITHOUT thinking blocks
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

        # Set chat history WITHOUT thinking blocks
        context._chat_history = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "The answer is 4"},
        ]

        # Count tokens
        compacter.count_tokens(context, "claude-sonnet-4-20250514")

        # Verify thinking was NOT enabled
        self.assertFalse(
            mock_client.thinking_enabled,
            "thinking parameter should not be enabled when no thinking blocks present",
        )

        """Test the real-world scenario: thinking on, then off.

        This reproduces the actual bug:
        1. User enables thinking and gets response with thinking blocks
        2. User disables thinking and continues conversation
        3. Token counting should enable thinking parameter (old message has thinking)
        4. API should accept this even though new response won't have thinking
        """

        class MockClient:
            def __init__(self):
                self.thinking_enabled = False
                self.messages = self.MessagesClient(self)

            class MessagesClient:
                def __init__(self, parent):
                    self.parent = parent

                def count_tokens(
                    self, model, system=None, messages=None, tools=None, thinking=None
                ):
                    if thinking is not None:
                        self.parent.thinking_enabled = True

                    class TokenResponse:
                        def __init__(self):
                            self.input_tokens = 500

                    return TokenResponse()

        mock_client = MockClient()
        compacter = ConversationCompacter(client=mock_client)

        # Create context
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

        # Simulate the conversation flow:
        # Turn 1: User asks with thinking enabled
        # Turn 2: Assistant responds WITH thinking blocks
        # Turn 3: User asks again (thinking now disabled)
        # Turn 4: We're about to send to API - need to count tokens
        context._chat_history = [
            {"role": "user", "content": "What is 2+2?"},
            {
                "role": "assistant",
                "content": [
                    ThinkingBlock(
                        signature="test_sig", thinking="Let me think", type="thinking"
                    ),
                    TextBlock(text="The answer is 4", type="text"),
                ],
            },
            {"role": "user", "content": "What is 3+3?"},
        ]

        # Count tokens before sending request
        # This should ENABLE thinking because message[1] has thinking blocks
        token_count = compacter.count_tokens(context, "claude-sonnet-4-20250514")

        # Verify thinking WAS enabled (this is correct behavior)
        self.assertTrue(
            mock_client.thinking_enabled,
            "thinking parameter SHOULD be enabled when history contains thinking blocks",
        )
        self.assertEqual(token_count, 500)


if __name__ == "__main__":
    unittest.main()

    def test_thinking_mode_switch_scenario(self):
        """Test the real-world scenario: thinking on, then off.

        This reproduces the actual bug:
        1. User enables thinking and gets response with thinking blocks
        2. User disables thinking and continues conversation
        3. Token counting should enable thinking parameter (old message has thinking)
        4. API should accept this even though new response won't have thinking
        """

        class MockClient:
            def __init__(self):
                self.thinking_enabled = False
                self.messages = self.MessagesClient(self)

            class MessagesClient:
                def __init__(self, parent):
                    self.parent = parent

                def count_tokens(
                    self, model, system=None, messages=None, tools=None, thinking=None
                ):
                    if thinking is not None:
                        self.parent.thinking_enabled = True

                    class TokenResponse:
                        def __init__(self):
                            self.input_tokens = 500

                    return TokenResponse()

        mock_client = MockClient()
        compacter = ConversationCompacter(client=mock_client)

        # Create context
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

        # Simulate conversation: thinking enabled, then disabled
        context._chat_history = [
            {"role": "user", "content": "What is 2+2?"},
            {
                "role": "assistant",
                "content": [
                    ThinkingBlock(
                        signature="test_sig", thinking="Let me think", type="thinking"
                    ),
                    TextBlock(text="The answer is 4", type="text"),
                ],
            },
            {"role": "user", "content": "What is 3+3?"},
        ]

        # Count tokens - should enable thinking
        token_count = compacter.count_tokens(context, "claude-sonnet-4-20250514")

        self.assertTrue(
            mock_client.thinking_enabled,
            "thinking parameter SHOULD be enabled when history contains thinking blocks",
        )
        self.assertEqual(token_count, 500)
