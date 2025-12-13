#!/usr/bin/env python3
"""
Unit tests for the conversation compaction validation module.
"""

import unittest
from silica.developer.compaction_validation import (
    validate_message_structure,
    validate_compacted_messages,
    validate_api_compatibility,
    strip_orphaned_tool_results,
    ValidationLevel,
)


class TestCompactionValidation(unittest.TestCase):
    """Tests for conversation compaction validation."""

    def test_valid_simple_conversation(self):
        """Test validation of a simple valid conversation."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! How can I help?"},
            {"role": "user", "content": "What's the weather?"},
            {"role": "assistant", "content": "I don't have weather data."},
        ]

        report = validate_message_structure(messages)

        self.assertTrue(report.is_valid)
        self.assertEqual(report.message_count, 4)
        self.assertEqual(report.tool_use_count, 0)
        self.assertEqual(report.tool_result_count, 0)
        self.assertFalse(report.has_errors())

    def test_invalid_role(self):
        """Test detection of invalid message role."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "system", "content": "This is wrong"},  # Invalid role
        ]

        report = validate_message_structure(messages)

        self.assertFalse(report.is_valid)
        self.assertTrue(report.has_errors())

        # Should have an error about invalid role
        error_messages = [
            i.message for i in report.issues if i.level == ValidationLevel.ERROR
        ]
        self.assertTrue(any("Invalid message role" in msg for msg in error_messages))

    def test_non_alternating_messages(self):
        """Test detection of non-alternating messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "Are you there?"},  # Non-alternating
            {"role": "assistant", "content": "Yes!"},
        ]

        report = validate_message_structure(messages)

        # Non-alternating is a warning, not an error
        self.assertTrue(report.is_valid)
        self.assertTrue(report.has_warnings())

        warning_messages = [
            i.message for i in report.issues if i.level == ValidationLevel.WARNING
        ]
        self.assertTrue(any("Non-alternating" in msg for msg in warning_messages))

    def test_valid_tool_use(self):
        """Test validation of valid tool use and result."""
        messages = [
            {"role": "user", "content": "What's 2+2?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me calculate that."},
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "calculator",
                        "input": {"expression": "2+2"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool_1", "content": "4"}
                ],
            },
            {"role": "assistant", "content": "The answer is 4."},
        ]

        report = validate_message_structure(messages)

        self.assertTrue(report.is_valid)
        self.assertEqual(report.tool_use_count, 1)
        self.assertEqual(report.tool_result_count, 1)
        self.assertFalse(report.has_errors())

    def test_tool_use_without_result(self):
        """Test detection of tool_use without corresponding tool_result."""
        messages = [
            {"role": "user", "content": "What's 2+2?"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "calculator",
                        "input": {"expression": "2+2"},
                    }
                ],
            },
            {"role": "user", "content": "Never mind"},  # No tool_result provided
            {"role": "assistant", "content": "Okay."},
        ]

        report = validate_message_structure(messages)

        self.assertFalse(report.is_valid)
        self.assertTrue(report.has_errors())

        error_messages = [
            i.message for i in report.issues if i.level == ValidationLevel.ERROR
        ]
        self.assertTrue(any("Tool use without result" in msg for msg in error_messages))

    def test_incomplete_tool_use_last_message(self):
        """Test that incomplete tool use in last message is INFO, not ERROR."""
        messages = [
            {"role": "user", "content": "What's 2+2?"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "calculator",
                        "input": {"expression": "2+2"},
                    }
                ],
            },
        ]

        report = validate_message_structure(messages)

        # Should be valid since it's in progress
        self.assertTrue(report.is_valid)
        self.assertFalse(report.has_errors())

        # But should have an INFO issue
        info_messages = [
            i.message for i in report.issues if i.level == ValidationLevel.INFO
        ]
        self.assertTrue(any("Incomplete tool use" in msg for msg in info_messages))

    def test_tool_result_without_use(self):
        """Test detection of tool_result without corresponding tool_use."""
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "nonexistent",
                        "content": "Result",
                    }
                ],
            },
        ]

        report = validate_message_structure(messages)

        self.assertFalse(report.is_valid)
        self.assertTrue(report.has_errors())

        error_messages = [
            i.message for i in report.issues if i.level == ValidationLevel.ERROR
        ]
        self.assertTrue(any("unknown tool_use_id" in msg for msg in error_messages))

    def test_missing_tool_use_id(self):
        """Test detection of tool_use without id field."""
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "calculator",
                        "input": {},
                        # Missing "id" field
                    }
                ],
            },
        ]

        report = validate_message_structure(messages)

        self.assertFalse(report.is_valid)
        self.assertTrue(report.has_errors())

        error_messages = [
            i.message for i in report.issues if i.level == ValidationLevel.ERROR
        ]
        self.assertTrue(any("missing 'id' field" in msg for msg in error_messages))

    def test_compacted_messages_validation(self):
        """Test validation of compacted messages."""
        original_messages = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Message 3"},
            {"role": "assistant", "content": "Response 3"},
        ]

        # Compacted should have summary + last 2 turns (4 messages)
        compacted_messages = [
            {
                "role": "user",
                "content": "### Conversation Summary\n\nPrevious discussion...",
            },
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Message 3"},
            {"role": "assistant", "content": "Response 3"},
        ]

        report = validate_compacted_messages(
            compacted_messages, original_messages, preserved_turns=2
        )

        # Should be valid
        self.assertTrue(report.is_valid)
        self.assertFalse(report.has_errors())

    def test_api_compatibility_must_start_with_user(self):
        """Test API compatibility check for starting with user message."""
        messages = [
            {
                "role": "assistant",
                "content": "Hello!",
            },  # Invalid - can't start with assistant
            {"role": "user", "content": "Hi"},
        ]

        report = validate_api_compatibility(messages)

        self.assertFalse(report.is_valid)
        self.assertTrue(report.has_errors())

        error_messages = [
            i.message for i in report.issues if i.level == ValidationLevel.ERROR
        ]
        self.assertTrue(
            any("must start with a user message" in msg for msg in error_messages)
        )

    def test_duplicate_tool_use_id(self):
        """Test detection of duplicate tool_use ids."""
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tool_1", "name": "tool_a", "input": {}},
                    {
                        "type": "tool_use",
                        "id": "tool_1",  # Duplicate!
                        "name": "tool_b",
                        "input": {},
                    },
                ],
            },
        ]

        report = validate_message_structure(messages)

        self.assertFalse(report.is_valid)
        self.assertTrue(report.has_errors())

        error_messages = [
            i.message for i in report.issues if i.level == ValidationLevel.ERROR
        ]
        self.assertTrue(any("Duplicate tool_use id" in msg for msg in error_messages))

    def test_validation_report_summary(self):
        """Test ValidationReport summary generation."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "Anyone there?"},  # Warning: non-alternating
        ]

        report = validate_message_structure(messages)

        summary = report.summary()

        self.assertIn("VALID", summary)
        self.assertIn("Total Messages: 2", summary)
        self.assertIn("1 warnings", summary)


class TestStripOrphanedToolResults(unittest.TestCase):
    """Tests for strip_orphaned_tool_results function."""

    def test_no_orphans_returns_same_structure(self):
        """Test that valid conversations are unchanged."""
        messages = [
            {"role": "user", "content": "What's 2+2?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me calculate."},
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "calculator",
                        "input": {"expression": "2+2"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool_1", "content": "4"}
                ],
            },
            {"role": "assistant", "content": "The answer is 4."},
        ]

        result = strip_orphaned_tool_results(messages)

        # Should have same number of messages
        self.assertEqual(len(result), 4)
        # Should be valid
        report = validate_message_structure(result)
        self.assertTrue(report.is_valid)

    def test_removes_orphaned_tool_results(self):
        """Test removal of tool_results without matching tool_use."""
        # Simulates what happens after compaction splits a conversation
        messages = [
            {
                "role": "user",
                "content": "### Compacted Summary\n\nPrevious conversation...",
            },
            {
                "role": "user",
                "content": [
                    # This tool_result has no corresponding tool_use
                    {
                        "type": "tool_result",
                        "tool_use_id": "orphan_tool",
                        "content": "some result",
                    },
                    {"type": "text", "text": "Continue with next question"},
                ],
            },
            {"role": "assistant", "content": "Okay, what's your question?"},
        ]

        result = strip_orphaned_tool_results(messages)

        # Orphaned tool_result should be removed
        report = validate_message_structure(result)
        self.assertTrue(report.is_valid)
        self.assertEqual(report.tool_result_count, 0)

    def test_keeps_valid_tool_results(self):
        """Test that valid tool_results are kept."""
        messages = [
            {"role": "user", "content": "Test"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "valid_tool",
                        "name": "test_tool",
                        "input": {},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    # Orphan - should be removed
                    {
                        "type": "tool_result",
                        "tool_use_id": "orphan_tool",
                        "content": "orphan",
                    },
                    # Valid - should be kept
                    {
                        "type": "tool_result",
                        "tool_use_id": "valid_tool",
                        "content": "valid result",
                    },
                ],
            },
            {"role": "assistant", "content": "Done."},
        ]

        result = strip_orphaned_tool_results(messages)

        report = validate_message_structure(result)
        self.assertTrue(report.is_valid)
        self.assertEqual(report.tool_result_count, 1)
        self.assertEqual(report.tool_use_count, 1)

    def test_removes_empty_user_messages(self):
        """Test that user messages with only orphaned tool_results are removed."""
        messages = [
            {"role": "user", "content": "Summary..."},
            {
                "role": "user",
                "content": [
                    # This message ONLY contains orphaned tool_results
                    {
                        "type": "tool_result",
                        "tool_use_id": "orphan_1",
                        "content": "result1",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "orphan_2",
                        "content": "result2",
                    },
                ],
            },
            {"role": "assistant", "content": "Hello"},
        ]

        result = strip_orphaned_tool_results(messages)

        # The second user message should be merged with the first
        # (both are user messages after orphan removal empties the second)
        self.assertEqual(len(result), 2)  # Summary + assistant
        report = validate_message_structure(result)
        self.assertTrue(report.is_valid)

    def test_merges_consecutive_user_messages(self):
        """Test that consecutive user messages are merged after cleanup."""
        messages = [
            {"role": "user", "content": "First message"},
            {
                "role": "user",
                "content": [
                    # After removing orphan, this becomes a user message with just text
                    {
                        "type": "tool_result",
                        "tool_use_id": "orphan",
                        "content": "result",
                    },
                    {"type": "text", "text": "Second message"},
                ],
            },
            {"role": "assistant", "content": "Response"},
        ]

        result = strip_orphaned_tool_results(messages)

        # Should merge the user messages
        self.assertEqual(len(result), 2)
        # First message should be a user message with merged content
        self.assertEqual(result[0]["role"], "user")
        report = validate_message_structure(result)
        self.assertTrue(report.is_valid)

    def test_handles_string_content(self):
        """Test handling of string content in messages."""
        messages = [
            {"role": "user", "content": "Simple string content"},
            {"role": "assistant", "content": "Response"},
        ]

        result = strip_orphaned_tool_results(messages)

        self.assertEqual(len(result), 2)
        report = validate_message_structure(result)
        self.assertTrue(report.is_valid)

    def test_does_not_modify_original(self):
        """Test that the original messages are not modified."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "orphan",
                        "content": "result",
                    }
                ],
            },
            {"role": "assistant", "content": "Response"},
        ]

        # Call the function (we don't need the result, just checking side effects)
        strip_orphaned_tool_results(messages)

        # Original should be unchanged
        self.assertEqual(len(messages[0]["content"]), 1)
        self.assertEqual(messages[0]["content"][0]["type"], "tool_result")

    def test_multiple_orphans_from_compaction(self):
        """Test realistic scenario from compaction with multiple orphaned tool_results."""
        # This simulates what happens when compaction splits mid-tool-execution
        messages = [
            {
                "role": "user",
                "content": "### Compacted Summary (first 5 turns)\n\n"
                "The user asked me to perform several operations...\n\n"
                "---\n\nContinuing with remaining conversation...",
            },
            {
                "role": "user",
                "content": [
                    # All of these tool_uses were in the compacted portion
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_014mgmGERbxJE65aLv2tf8ct",
                        "content": "File written successfully",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc123",
                        "content": "Command executed",
                    },
                ],
            },
            {
                "role": "assistant",
                "content": "Great, I've completed those operations. What's next?",
            },
            {"role": "user", "content": "Now do something else"},
        ]

        result = strip_orphaned_tool_results(messages)

        # Should be valid after cleanup
        report = validate_message_structure(result)
        self.assertTrue(
            report.is_valid, f"Expected valid messages, got: {report.detailed_report()}"
        )

        # Orphaned tool_results should be gone
        self.assertEqual(report.tool_result_count, 0)


if __name__ == "__main__":
    unittest.main()
