#!/usr/bin/env python3
"""Tests for compaction during non-tool-use cycles.

This addresses a critical bug where compaction only ran inside the `else` branch
of the agent loop (when tool_result_buffer was non-empty). For pure text response
cycles (e.g., coordinator heartbeats where the agent responds "✓" with no tool calls),
the else branch was never reached, and context grew without bound.

The fix adds a compaction check after every API response (when stop_reason != "tool_use"),
ensuring heartbeat/text-only cycles trigger compaction.
"""

import unittest
from unittest import mock
import tempfile
import shutil

from silica.developer.context import AgentContext
from silica.developer.compacter import ConversationCompacter, CompactionMetadata
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.memory import MemoryManager

from tests.developer.conftest import MockAnthropicClient, MockUserInterface


class TestCompactionNonToolCycles(unittest.TestCase):
    """Tests for compaction during non-tool-use cycles (heartbeats, pure text)."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()

        # Model spec with context window
        self.model_spec = {
            "title": "claude-test-model",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 1000,
        }

        # Build a realistic heartbeat conversation (alternating user/assistant)
        self.heartbeat_messages = []
        for i in range(20):
            self.heartbeat_messages.append(
                {
                    "role": "user",
                    "content": f"[Heartbeat: 2026-03-01T{10 + i}:00:00Z]\n\nCheck feeds and messages.",
                }
            )
            self.heartbeat_messages.append({"role": "assistant", "content": "✓"})

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    @mock.patch("anthropic.Client")
    def test_compaction_check_runs_with_force(self, mock_client_class):
        """Test that force=True bypasses the threshold check."""
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

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
        context._chat_history = self.heartbeat_messages.copy()

        metadata = CompactionMetadata(
            archive_name="pre-compaction-test.json",
            original_message_count=40,
            compacted_message_count=2,
            original_token_count=5000,
            summary_token_count=500,
            compaction_ratio=0.1,
        )

        with mock.patch.object(
            ConversationCompacter, "compact_conversation", return_value=metadata
        ) as mock_compact:
            compacter = ConversationCompacter(client=mock_client)
            updated_context, compaction_applied = compacter.check_and_apply_compaction(
                context,
                self.model_spec["title"],
                ui,
                enable_compaction=True,
                force=True,
            )

            self.assertTrue(compaction_applied)
            # Verify compact_conversation was called with force=True
            mock_compact.assert_called_once()
            call_kwargs = mock_compact.call_args
            self.assertTrue(
                call_kwargs[1].get("force", False) or call_kwargs[0][3]
                if len(call_kwargs[0]) > 3
                else call_kwargs[1].get("force", False)
            )

    @mock.patch("anthropic.Client")
    def test_compaction_check_with_no_tool_buffer(self, mock_client_class):
        """Test that compaction check works when tool_result_buffer is empty.

        This simulates the heartbeat scenario: messages exist but no pending
        tool results. Previously, this path skipped compaction entirely because
        the check was inside the else branch (tool results present).
        """
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

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
        context._chat_history = self.heartbeat_messages.copy()
        # Explicitly ensure no pending tool results
        context.tool_result_buffer.clear()

        metadata = CompactionMetadata(
            archive_name="pre-compaction-test.json",
            original_message_count=40,
            compacted_message_count=2,
            original_token_count=5000,
            summary_token_count=500,
            compaction_ratio=0.1,
        )

        with mock.patch.object(
            ConversationCompacter, "compact_conversation", return_value=metadata
        ):
            compacter = ConversationCompacter(client=mock_client)
            updated_context, compaction_applied = compacter.check_and_apply_compaction(
                context,
                self.model_spec["title"],
                ui,
                enable_compaction=True,
            )

            # With empty tool_result_buffer, should still be able to compact
            # (the tool_result_buffer check should NOT prevent compaction)
            self.assertTrue(compaction_applied)

    @mock.patch("anthropic.Client")
    def test_force_bypasses_threshold(self, mock_client_class):
        """Test that force=True compacts even with a small conversation."""
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

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
        # Only 4 messages - normally too few for compaction threshold
        context._chat_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "Bye"},
            {"role": "assistant", "content": "Goodbye!"},
        ]

        metadata = CompactionMetadata(
            archive_name="pre-compaction-test.json",
            original_message_count=4,
            compacted_message_count=2,
            original_token_count=100,
            summary_token_count=50,
            compaction_ratio=0.5,
        )

        with mock.patch.object(
            ConversationCompacter, "compact_conversation", return_value=metadata
        ) as mock_compact:
            compacter = ConversationCompacter(client=mock_client)
            updated_context, compaction_applied = compacter.check_and_apply_compaction(
                context,
                self.model_spec["title"],
                ui,
                enable_compaction=True,
                force=True,
            )

            self.assertTrue(compaction_applied)
            mock_compact.assert_called_once()

    @mock.patch("anthropic.Client")
    def test_force_still_requires_minimum_messages(self, mock_client_class):
        """Test that force=True still respects the minimum 2-message requirement."""
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

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
        context._chat_history = [
            {"role": "user", "content": "Hello"},
        ]

        compacter = ConversationCompacter(client=mock_client)
        updated_context, compaction_applied = compacter.check_and_apply_compaction(
            context,
            self.model_spec["title"],
            ui,
            enable_compaction=True,
            force=True,
        )

        # Should not compact with only 1 message, even with force
        self.assertFalse(compaction_applied)


class TestEmergencyTruncation(unittest.TestCase):
    """Tests for the brute-force emergency truncation fallback."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.model_spec = {
            "title": "claude-test-model",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 1000,
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_emergency_truncate_drops_oldest_half(self):
        """Test that emergency truncation drops the oldest half of messages."""
        from silica.developer.agent_loop import _emergency_truncate

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

        # Build 20 messages (10 user/assistant pairs)
        messages = []
        for i in range(10):
            messages.append({"role": "user", "content": f"User message {i}"})
            messages.append({"role": "assistant", "content": f"Assistant response {i}"})
        context._chat_history = messages

        _emergency_truncate(context, ui)

        # Should have roughly half the messages + 1 truncation notice
        # Original: 20 messages, midpoint = 10, keep messages[10:]  = 10 messages + 1 notice = 11
        self.assertEqual(len(context.chat_history), 11)

        # First message should be the truncation notice
        self.assertIn(
            "EMERGENCY CONTEXT TRUNCATION", context.chat_history[0]["content"]
        )

        # Should have dropped 10 messages
        self.assertIn("10 oldest messages", ui.system_messages[-1])

    def test_emergency_truncate_preserves_role_alternation(self):
        """Test that truncation starts on a user message."""
        from silica.developer.agent_loop import _emergency_truncate

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

        # 5 messages: midpoint = 2 (assistant), should advance to 3 (user)
        messages = [
            {"role": "user", "content": "msg 0"},
            {"role": "assistant", "content": "msg 1"},
            {"role": "user", "content": "msg 2"},  # index 2 = midpoint for 5 msgs
            {"role": "assistant", "content": "msg 3"},
            {"role": "user", "content": "msg 4"},
        ]
        context._chat_history = messages

        _emergency_truncate(context, ui)

        # First message after truncation notice should be a user message
        # (the truncation notice itself is role=user, and the kept portion starts with user)
        self.assertEqual(context.chat_history[0]["role"], "user")
        # The kept messages should start with a user message
        self.assertEqual(context.chat_history[1]["role"], "user")

    def test_emergency_truncate_noop_for_tiny_history(self):
        """Test that truncation does nothing for very small histories."""
        from silica.developer.agent_loop import _emergency_truncate

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

        context._chat_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]

        _emergency_truncate(context, ui)

        # Should not truncate 2 or fewer messages
        self.assertEqual(len(context.chat_history), 2)


class TestEmergencyCompactionInAgentLoop(unittest.TestCase):
    """Test the emergency compaction path in the agent loop error handler.

    These tests verify that when the API returns 'prompt is too long',
    the agent loop forces compaction before retrying.
    """

    def test_compaction_check_placement_in_agent_loop(self):
        """Verify that the compaction check exists after assistant message append
        and not only in the tool-result else branch.

        This is a code structure test - it reads the source and verifies the fix
        is in the right place.
        """
        import inspect
        from silica.developer import agent_loop

        source = inspect.getsource(agent_loop.run)

        # The compaction check should appear after "handle_assistant_message"
        # and before the tool_use check, for non-tool-use responses
        assistant_msg_idx = source.find(
            "user_interface.handle_assistant_message(ai_response)"
        )
        assert assistant_msg_idx > 0, "Could not find handle_assistant_message call"

        # Find the compaction check that follows it
        # It should be between handle_assistant_message and stop_reason == "tool_use"
        after_assistant = source[assistant_msg_idx:]
        tool_use_check_idx = after_assistant.find(
            'final_message.stop_reason == "tool_use"'
        )
        assert tool_use_check_idx > 0, "Could not find tool_use stop_reason check"

        compaction_section = after_assistant[:tool_use_check_idx]

        # Verify the new compaction check is present
        assert "check_and_apply_compaction" in compaction_section, (
            "Compaction check should appear between handle_assistant_message "
            "and the tool_use stop_reason check"
        )
        assert 'stop_reason != "tool_use"' in compaction_section, (
            "Compaction check should be gated on non-tool-use responses"
        )

    def test_emergency_compaction_in_error_handler(self):
        """Verify that the 'prompt is too long' error handler includes emergency compaction.

        This is a code structure test.
        """
        import inspect
        from silica.developer import agent_loop

        source = inspect.getsource(agent_loop.run)

        # Find the "prompt is too long" error handler
        error_handler_idx = source.find('"prompt is too long"')
        assert error_handler_idx > 0, "Could not find 'prompt is too long' handler"

        # Get the section after that
        after_error = source[error_handler_idx : error_handler_idx + 4000]

        # Verify emergency compaction is present
        assert "emergency compaction" in after_error.lower(), (
            "Emergency compaction should be triggered on 'prompt is too long' errors"
        )
        assert "force=True" in after_error, (
            "Emergency compaction should use force=True to bypass threshold"
        )

        # Verify brute-force truncation fallback when compaction fails
        assert "_emergency_truncate" in after_error, (
            "Emergency truncation should be called when compaction itself fails"
        )


if __name__ == "__main__":
    unittest.main()
