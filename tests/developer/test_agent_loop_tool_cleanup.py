#!/usr/bin/env python3
"""Tests for tool block cleanup in the agent loop."""

import unittest
from silica.developer.compaction_validation import (
    strip_orphaned_tool_blocks,
    validate_message_structure,
)


class TestStripOrphanedToolBlocksEdgeCases(unittest.TestCase):
    """Test edge cases in strip_orphaned_tool_blocks that can cause API errors."""

    def test_tool_use_in_middle_of_conversation_without_result(self):
        """Test that tool_use without tool_result in the middle of conversation is removed.

        This is the case from the error:
        messages.25: `tool_use` ids were found without `tool_result` blocks immediately after
        """
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll help with that."},
                    {
                        "type": "tool_use",
                        "id": "toolu_01NHptmsByaaDZ5PowH2crLU",
                        "name": "shell_execute",
                        "input": {"command": "ls"},
                    },
                ],
            },
            # No tool_result for the above tool_use!
            {"role": "user", "content": "continue"},
            {"role": "assistant", "content": "Okay, continuing..."},
        ]

        result = strip_orphaned_tool_blocks(messages)

        # Should be valid after cleanup
        report = validate_message_structure(result)
        self.assertTrue(
            report.is_valid,
            f"Messages should be valid after cleanup: {report.detailed_report()}",
        )
        # The orphaned tool_use should be removed
        self.assertEqual(report.tool_use_count, 0)

    def test_cleanup_preserves_message_count_but_removes_tool_blocks(self):
        """Test that cleanup can modify messages without changing count.

        This catches the bug where we only checked if message count changed.
        """
        messages = [
            {"role": "user", "content": "Do something"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll run a command."},
                    {
                        "type": "tool_use",
                        "id": "orphan_tool_1",
                        "name": "shell_execute",
                        "input": {"command": "echo hello"},
                    },
                ],
            },
            # The next user message has text content but no tool_result
            {"role": "user", "content": "Thanks, what's next?"},
            {"role": "assistant", "content": "Let me help you with that."},
        ]

        len(messages)
        result = strip_orphaned_tool_blocks(messages)

        # Message count might be the same (assistant message still has text)
        # But the tool_use should be removed
        report = validate_message_structure(result)
        self.assertTrue(
            report.is_valid,
            f"Messages should be valid: {report.detailed_report()}",
        )
        self.assertEqual(
            report.tool_use_count, 0, "Orphaned tool_use should be removed"
        )

    def test_multiple_tool_uses_some_orphaned(self):
        """Test that only orphaned tool_uses are removed, paired ones kept."""
        messages = [
            {"role": "user", "content": "Run two commands"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Running commands..."},
                    {
                        "type": "tool_use",
                        "id": "tool_with_result",
                        "name": "shell_execute",
                        "input": {"command": "echo 1"},
                    },
                    {
                        "type": "tool_use",
                        "id": "tool_without_result",
                        "name": "shell_execute",
                        "input": {"command": "echo 2"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    # Only one tool_result - the other tool_use is orphaned
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_with_result",
                        "content": "1",
                    },
                ],
            },
            {"role": "assistant", "content": "Done!"},
        ]

        result = strip_orphaned_tool_blocks(messages)

        report = validate_message_structure(result)
        self.assertTrue(
            report.is_valid,
            f"Messages should be valid: {report.detailed_report()}",
        )
        # Only the paired tool_use/tool_result should remain
        self.assertEqual(report.tool_use_count, 1)
        self.assertEqual(report.tool_result_count, 1)

    def test_max_tokens_scenario(self):
        """Simulate the max_tokens scenario that causes orphaned tool blocks.

        When max_tokens is hit, the assistant message (with tool_use) is removed,
        but the user's next message might reference continuing, creating an
        invalid state. We test the broken state where the assistant message
        was removed.
        """
        # Broken conversation where the assistant message was removed due to max_tokens:
        broken_messages = [
            {"role": "user", "content": "Write a long file"},
            # Assistant message with tool_use was REMOVED due to max_tokens
            {
                "role": "user",
                "content": [
                    # But the tool_result remains - orphaned!
                    {
                        "type": "tool_result",
                        "tool_use_id": "write_file_tool",
                        "content": "File written successfully",
                    },
                ],
            },
            {"role": "user", "content": "continue"},
        ]

        result = strip_orphaned_tool_blocks(broken_messages)

        report = validate_message_structure(result)
        self.assertTrue(
            report.is_valid,
            f"Messages should be valid after cleanup: {report.detailed_report()}",
        )
        self.assertEqual(
            report.tool_result_count, 0, "Orphaned tool_result should be removed"
        )

    def test_compaction_split_scenario(self):
        """Simulate the compaction split scenario.

        After compaction, we might have:
        1. Summary message (user)
        2. tool_result without tool_use (user) - tool_use was summarized
        3. Assistant response
        """
        messages = [
            {
                "role": "user",
                "content": "### Compacted Summary (first 10 turns)\n\nPrevious work...",
            },
            {
                "role": "user",
                "content": [
                    # Orphaned tool_results - their tool_uses were compacted
                    {
                        "type": "tool_result",
                        "tool_use_id": "compacted_tool_1",
                        "content": "Result 1",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "compacted_tool_2",
                        "content": "Result 2",
                    },
                ],
            },
            {
                "role": "assistant",
                "content": "Great, continuing from where we left off...",
            },
            {"role": "user", "content": "Now do something new"},
        ]

        result = strip_orphaned_tool_blocks(messages)

        report = validate_message_structure(result)
        self.assertTrue(
            report.is_valid,
            f"Messages should be valid: {report.detailed_report()}",
        )
        self.assertEqual(report.tool_result_count, 0)

    def test_cleanup_is_idempotent(self):
        """Test that running cleanup multiple times gives the same result."""
        messages = [
            {"role": "user", "content": "Test"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Running..."},
                    {
                        "type": "tool_use",
                        "id": "orphan",
                        "name": "test",
                        "input": {},
                    },
                ],
            },
            {"role": "user", "content": "Continue"},
        ]

        result1 = strip_orphaned_tool_blocks(messages)
        result2 = strip_orphaned_tool_blocks(result1)
        result3 = strip_orphaned_tool_blocks(result2)

        # All results should be the same
        self.assertEqual(len(result1), len(result2))
        self.assertEqual(len(result2), len(result3))

        # All should be valid
        for result in [result1, result2, result3]:
            report = validate_message_structure(result)
            self.assertTrue(report.is_valid)

    def test_handles_sdk_objects(self):
        """Test that cleanup works with Anthropic SDK objects, not just dicts.

        When the assistant responds, the content contains SDK objects like
        ToolUseBlock, not plain dicts. The cleanup must handle both.
        """
        from unittest.mock import MagicMock

        # Create mock SDK objects that mimic ToolUseBlock
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.id = "toolu_SDK_OBJECT_TEST"
        tool_use_block.name = "test_tool"
        tool_use_block.input = {}

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "I'll help with that."

        messages = [
            {"role": "user", "content": "Do something"},
            {
                "role": "assistant",
                "content": [text_block, tool_use_block],  # SDK objects, not dicts!
            },
            # No tool_result - the tool_use is orphaned
            {"role": "user", "content": "Continue please"},
        ]

        result = strip_orphaned_tool_blocks(messages)

        # The orphaned tool_use should be removed
        validate_message_structure(result)
        # Note: validation may not work perfectly with mock objects,
        # but at minimum the SDK objects should be detected and filtered

        # Check that the tool_use was removed from the assistant message
        assistant_msg = None
        for msg in result:
            if msg.get("role") == "assistant":
                assistant_msg = msg
                break

        self.assertIsNotNone(assistant_msg)
        # The tool_use block should have been removed
        content = assistant_msg.get("content", [])
        tool_uses_in_result = [
            b
            for b in content
            if (isinstance(b, dict) and b.get("type") == "tool_use")
            or (hasattr(b, "type") and b.type == "tool_use")
        ]
        self.assertEqual(
            len(tool_uses_in_result), 0, "Orphaned SDK tool_use should be removed"
        )


if __name__ == "__main__":
    unittest.main()
