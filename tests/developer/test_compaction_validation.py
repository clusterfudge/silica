#!/usr/bin/env python3
"""
Unit tests for the conversation compaction validation module.
"""

import unittest
from silica.developer.compaction_validation import (
    validate_message_structure,
    validate_compacted_messages,
    validate_api_compatibility,
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


if __name__ == "__main__":
    unittest.main()
