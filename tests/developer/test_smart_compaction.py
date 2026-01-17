#!/usr/bin/env python3
"""
Unit tests for the smart compaction functionality.

Tests the token-based turn calculation that aims for 30% reduction.
"""

import unittest
from unittest import mock
from pathlib import Path
import tempfile
import shutil

from silica.developer.compacter import (
    ConversationCompacter,
    DEFAULT_MIN_REDUCTION_RATIO,
)
from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.memory import MemoryManager

# Import shared test fixtures
from tests.developer.conftest import MockAnthropicClient, MockUserInterface


class TestSmartCompaction(unittest.TestCase):
    """Tests for the smart compaction turn calculation."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.model_spec = {
            "title": "claude-opus-4-5-20251101",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 200000,
        }

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    def _create_context_with_messages(self, messages):
        """Helper to create an AgentContext with given messages."""
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-session-smart",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
        )
        context._chat_history = messages
        return context

    def test_default_min_reduction_ratio(self):
        """Test that default min reduction ratio is 30%."""
        self.assertEqual(DEFAULT_MIN_REDUCTION_RATIO, 0.30)

    def test_min_reduction_ratio_from_environment(self):
        """Test that min reduction ratio can be configured via environment."""
        with mock.patch.dict("os.environ", {"SILICA_COMPACTION_MIN_REDUCTION": "0.40"}):
            mock_client = MockAnthropicClient()
            compacter = ConversationCompacter(client=mock_client)
            self.assertEqual(compacter.min_reduction_ratio, 0.40)

    def test_invalid_min_reduction_from_environment(self):
        """Test that invalid min reduction falls back to default."""
        with mock.patch.dict(
            "os.environ", {"SILICA_COMPACTION_MIN_REDUCTION": "invalid"}
        ):
            mock_client = MockAnthropicClient()
            compacter = ConversationCompacter(client=mock_client)
            self.assertEqual(compacter.min_reduction_ratio, DEFAULT_MIN_REDUCTION_RATIO)

    def test_estimate_message_tokens(self):
        """Test token estimation for individual messages."""
        mock_client = MockAnthropicClient()
        compacter = ConversationCompacter(client=mock_client)

        # Simple text message
        simple_msg = {"role": "user", "content": "Hello world"}
        tokens = compacter._estimate_message_tokens(simple_msg)
        self.assertGreater(tokens, 0)

        # Message with tool use
        tool_msg = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me check that"},
                {
                    "type": "tool_use",
                    "name": "read_file",
                    "input": {"path": "/some/path.py"},
                },
            ],
        }
        tool_tokens = compacter._estimate_message_tokens(tool_msg)
        self.assertGreater(tool_tokens, tokens)  # Should be larger

    def test_calculate_turns_for_target_reduction_minimum(self):
        """Test that calculation returns at least 1 turn."""
        mock_client = MockAnthropicClient(token_count=1000)
        compacter = ConversationCompacter(client=mock_client)

        # Very small conversation
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        context = self._create_context_with_messages(messages)

        turns = compacter.calculate_turns_for_target_reduction(context, "sonnet")
        self.assertGreaterEqual(turns, 1)

    def test_calculate_turns_scales_with_content(self):
        """Test that more content leads to more turns to compact."""
        mock_client = MockAnthropicClient(token_count=50000)
        compacter = ConversationCompacter(client=mock_client)

        # Create a conversation with varying message sizes
        small_messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Thanks"},
        ]

        large_messages = [
            {"role": "user", "content": "Hi " * 100},
            {"role": "assistant", "content": "Hello " * 200},
            {"role": "user", "content": "Thanks " * 100},
            {"role": "assistant", "content": "You're welcome " * 200},
            {"role": "user", "content": "Bye " * 100},
        ]

        small_context = self._create_context_with_messages(small_messages)
        large_context = self._create_context_with_messages(large_messages)

        small_turns = compacter.calculate_turns_for_target_reduction(
            small_context, "sonnet"
        )
        large_turns = compacter.calculate_turns_for_target_reduction(
            large_context, "sonnet"
        )

        # Large conversation should need more turns to hit 30% reduction
        # (or at least not fewer)
        self.assertGreaterEqual(large_turns, small_turns)

    def test_auto_turn_calculation_in_compact_conversation(self):
        """Test that compact_conversation uses auto-calculation when turns=None."""
        mock_client = MockAnthropicClient(token_count=50000)
        compacter = ConversationCompacter(client=mock_client)

        # Create a conversation
        messages = [
            {"role": "user", "content": "Hello " * 50},
            {"role": "assistant", "content": "Hi there! " * 100},
            {"role": "user", "content": "Can you help? " * 50},
            {"role": "assistant", "content": "Of course! " * 100},
            {"role": "user", "content": "Thanks " * 50},
        ]

        context = self._create_context_with_messages(messages)

        # Mock should_compact to return True
        compacter.should_compact = mock.MagicMock(return_value=True)

        # Track the calculate function being called
        original_calc = compacter.calculate_turns_for_target_reduction
        calc_called = []

        def tracked_calc(*args, **kwargs):
            calc_called.append(True)
            return original_calc(*args, **kwargs)

        compacter.calculate_turns_for_target_reduction = tracked_calc

        with mock.patch("pathlib.Path.home", return_value=Path(self.test_dir)):
            # Call with turns=None (auto-calculate)
            metadata = compacter.compact_conversation(context, "haiku", turns=None)

        # Verify auto-calculation was called
        self.assertTrue(len(calc_called) > 0, "Auto-calculation should be called")
        self.assertIsNotNone(metadata)

    def test_explicit_turns_bypasses_calculation(self):
        """Test that explicit turns parameter skips auto-calculation."""
        mock_client = MockAnthropicClient(token_count=50000)
        compacter = ConversationCompacter(client=mock_client)

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "Thanks"},
            {"role": "assistant", "content": "You're welcome!"},
            {"role": "user", "content": "Bye"},
        ]

        context = self._create_context_with_messages(messages)

        # Mock should_compact to return True
        compacter.should_compact = mock.MagicMock(return_value=True)

        # Track the calculate function
        calc_called = []
        original_calc = compacter.calculate_turns_for_target_reduction

        def tracked_calc(*args, **kwargs):
            calc_called.append(True)
            return original_calc(*args, **kwargs)

        compacter.calculate_turns_for_target_reduction = tracked_calc

        with mock.patch("pathlib.Path.home", return_value=Path(self.test_dir)):
            # Call with explicit turns=2
            metadata = compacter.compact_conversation(context, "haiku", turns=2)

        # Verify auto-calculation was NOT called
        self.assertEqual(
            len(calc_called),
            0,
            "Auto-calculation should not be called with explicit turns",
        )
        self.assertIsNotNone(metadata)

    def test_check_and_apply_uses_auto_calculation(self):
        """Test that check_and_apply_compaction uses auto turn calculation."""
        mock_client = MockAnthropicClient(token_count=90000)  # High token count
        compacter = ConversationCompacter(client=mock_client, threshold_ratio=0.8)

        # Override context window for predictable behavior
        compacter.model_context_windows = {"claude-opus-4-5-20251101": 100000}

        messages = [
            {"role": "user", "content": "Hello " * 100},
            {"role": "assistant", "content": "Hi there! " * 200},
            {"role": "user", "content": "Can you help? " * 100},
            {"role": "assistant", "content": "Of course! " * 200},
            {"role": "user", "content": "Thanks " * 100},
        ]

        context = self._create_context_with_messages(messages)
        ui = MockUserInterface()

        with mock.patch("pathlib.Path.home", return_value=Path(self.test_dir)):
            updated_context, compaction_applied = compacter.check_and_apply_compaction(
                context, "claude-opus-4-5-20251101", ui, enable_compaction=True
            )

        # Should have compacted
        self.assertTrue(compaction_applied)
        # Should have shown a message about the compaction
        self.assertTrue(
            any("compacted" in msg.lower() for msg in ui.system_messages),
            f"Expected compaction message, got: {ui.system_messages}",
        )


class TestSmartCompactionDebugOutput(unittest.TestCase):
    """Tests for debug output in smart compaction."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.model_spec = {
            "title": "claude-opus-4-5-20251101",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 200000,
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_debug_output_shows_calculation_details(self):
        """Test that debug mode shows detailed calculation info."""
        mock_client = MockAnthropicClient(token_count=50000)
        compacter = ConversationCompacter(client=mock_client)

        messages = [
            {"role": "user", "content": "Hello " * 100},
            {"role": "assistant", "content": "Hi there! " * 200},
            {"role": "user", "content": "Thanks " * 100},
        ]

        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-debug",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
        )
        context._chat_history = messages

        # Capture print output
        import io
        import sys

        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            compacter.calculate_turns_for_target_reduction(
                context, "sonnet", debug=True
            )
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()

        # Verify debug output contains key information
        self.assertIn("Smart Compaction Calculation", output)
        self.assertIn("Total tokens", output)
        self.assertIn("Target reduction", output)


if __name__ == "__main__":
    unittest.main()
