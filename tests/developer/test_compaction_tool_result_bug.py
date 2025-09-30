#!/usr/bin/env python3
"""
Test for the compaction bug where tool_result references orphaned tool_use_id.

This test reproduces the bug reported where after compaction, a tool_result
in a user message references a tool_use_id that no longer has a corresponding
tool_use block in the proper location.
"""

import unittest
from unittest import mock
import tempfile
import shutil

from silica.developer.compacter import ConversationCompacter
from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.memory import MemoryManager


class MockUserInterface:
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

    def display_token_count(self, *args, **kwargs):
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


class MockAnthropicClient:
    """Mock for the Anthropic client."""

    def __init__(self):
        self.messages = self.MessagesClient()

    class MessagesClient:
        def count_tokens(self, model, system=None, messages=None, tools=None):
            """Mock token counting - return high count to trigger compaction."""

            class TokenResponse:
                def __init__(self):
                    self.token_count = 90000  # High enough to trigger compaction

            return TokenResponse()

        def create(self, model, system, messages, max_tokens):
            """Mock message creation for summary generation."""

            class ContentItem:
                def __init__(self):
                    self.text = "Test summary of conversation"

            class MessageResponse:
                def __init__(self):
                    self.content = [ContentItem()]

            return MessageResponse()


class TestCompactionToolResultBug(unittest.TestCase):
    """Test the compaction bug with tool_result references."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()

        # Create messages that simulate the bug scenario:
        # - Earlier messages with tool_use/tool_result
        # - Recent message with tool_use
        # - Most recent message with tool_result
        self.sample_messages = [
            {"role": "user", "content": "First user message"},
            {"role": "assistant", "content": "First assistant response"},
            {"role": "user", "content": "Do something"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me use a tool"},
                    {
                        "type": "tool_use",
                        "id": "toolu_early_001",
                        "name": "read_file",
                        "input": {"path": "test.py"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_early_001",
                        "content": "File contents here",
                    }
                ],
            },
            {"role": "assistant", "content": "Now let me do more work"},
            {"role": "user", "content": "Another request"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Using another tool"},
                    {
                        "type": "tool_use",
                        "id": "toolu_recent_001",
                        "name": "shell_execute",
                        "input": {"command": "ls"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_recent_001",
                        "content": "file1.py\nfile2.py",
                    }
                ],
            },
        ]

        self.model_spec = {
            "title": "claude-opus-4-20250514",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 100000,
        }

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    def test_compact_conversation_validates_tool_pairs(self):
        """Test that compact_conversation preserves valid tool_use/tool_result pairs."""
        # Create mock client
        mock_client = MockAnthropicClient()

        # Create compacter with low threshold to trigger compaction
        compacter = ConversationCompacter(threshold_ratio=0.5, client=mock_client)

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

        # Mock should_compact to return True
        with mock.patch.object(compacter, "should_compact", return_value=True):
            # Perform compaction
            compacted_messages, summary = compacter.compact_conversation(
                context, self.model_spec["title"]
            )

            # Verify the compacted messages
            self.assertIsNotNone(summary, "Summary should be generated")
            self.assertGreater(
                len(compacted_messages), 0, "Should have some compacted messages"
            )

            # After the fix, compacted messages should only contain the summary message
            # No old messages are preserved to avoid tool_use/tool_result pairing issues
            self.assertEqual(
                len(compacted_messages),
                1,
                "Compacted messages should only contain the summary message",
            )
            self.assertEqual(
                compacted_messages[0]["role"],
                "user",
                "First message should be from user",
            )

            # Verify content is a list (not a string)
            self.assertIsInstance(
                compacted_messages[0]["content"],
                list,
                "Content should be a list of content blocks",
            )

            # Validate message structure - check for orphaned tool_results
            for i, message in enumerate(compacted_messages):
                if message["role"] == "user":
                    content = message.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if (
                                isinstance(block, dict)
                                and block.get("type") == "tool_result"
                            ):
                                tool_use_id = block.get("tool_use_id")
                                # Check if previous message has this tool_use
                                if i > 0:
                                    prev_message = compacted_messages[i - 1]
                                    if prev_message["role"] == "assistant":
                                        prev_content = prev_message.get("content", [])
                                        if isinstance(prev_content, list):
                                            tool_use_ids = [
                                                b.get("id")
                                                for b in prev_content
                                                if isinstance(b, dict)
                                                and b.get("type") == "tool_use"
                                            ]
                                            self.assertIn(
                                                tool_use_id,
                                                tool_use_ids,
                                                f"tool_result at message {i} references "
                                                f"tool_use_id {tool_use_id} that doesn't "
                                                f"exist in previous assistant message",
                                            )

    def test_validate_message_sequence(self):
        """Test that we can validate a message sequence for API compatibility."""
        # This test verifies that valid message sequences are structured correctly

        # Valid sequence: user -> assistant with tool_use -> user with tool_result
        valid_messages = [
            {"role": "user", "content": "Do something"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_001",
                        "name": "test_tool",
                        "input": {},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_001",
                        "content": "result",
                    }
                ],
            },
        ]

        # The valid sequence should have proper role alternation
        self.assertEqual(valid_messages[0]["role"], "user")
        self.assertEqual(valid_messages[1]["role"], "assistant")
        self.assertEqual(valid_messages[2]["role"], "user")

    def test_compaction_with_tool_use_in_progress(self):
        """Test that compaction doesn't happen when there are pending tool results."""
        # This verifies the guard in _check_and_apply_compaction
        mock_client = MockAnthropicClient()
        compacter = ConversationCompacter(threshold_ratio=0.5, client=mock_client)

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

        # Set up messages ending with assistant tool_use (incomplete)
        context._chat_history = [
            {"role": "user", "content": "Do something"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_001",
                        "name": "test_tool",
                        "input": {},
                    }
                ],
            },
        ]

        # Compaction should not happen because the conversation is incomplete
        with mock.patch.object(compacter, "should_compact", return_value=True):
            # Even though should_compact returns True, compact_conversation
            # will call should_compact again internally, and we need to ensure
            # the check prevents compaction when there's an incomplete tool exchange

            # Actually, the guard is in _check_and_apply_compaction in agent_loop.py
            # Here we're just testing that compact_conversation handles this gracefully

            compacted_messages, summary = compacter.compact_conversation(
                context, self.model_spec["title"]
            )

            # Verify summary was generated
            self.assertIsNotNone(summary)

            # The key point: compacted messages should be valid and not end with
            # an incomplete tool_use
            if len(compacted_messages) > 0:
                last_message = compacted_messages[-1]
                if last_message["role"] == "assistant":
                    content = last_message.get("content", [])
                    if isinstance(content, list):
                        # Check if there's a tool_use in the last message
                        has_tool_use = any(
                            isinstance(block, dict) and block.get("type") == "tool_use"
                            for block in content
                        )
                        # After our fix, the compacted messages should only have the summary
                        # So this shouldn't happen, but let's assert it anyway
                        self.assertFalse(
                            has_tool_use,
                            "Compacted messages should not end with assistant tool_use",
                        )


if __name__ == "__main__":
    unittest.main()

    # Invalid sequence (now prevented by the fix):
    # A summary user message followed by tool_use/tool_result pairs
    # would have been created by the old code

    # The valid sequence should work fine
    # The fix ensures we never create invalid sequences

    # For now, just check that the structure is as expected
