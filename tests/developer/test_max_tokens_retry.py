"""Tests for max_tokens retry handling in agent loop."""

from silica.developer.agent_loop import (
    _get_max_tokens_attempt_count,
    _create_max_tokens_retry_message,
)


class TestMaxTokensRetryHelpers:
    """Test the helper functions for max_tokens retry handling."""

    def test_get_attempt_count_empty_history(self):
        """Empty history should return 0 attempts."""
        assert _get_max_tokens_attempt_count([]) == 0

    def test_get_attempt_count_no_retry_messages(self):
        """History without retry messages should return 0."""
        history = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Hi!"}]},
        ]
        assert _get_max_tokens_attempt_count(history) == 0

    def test_get_attempt_count_one_retry(self):
        """Should count one [X] marker as 1 attempt."""
        history = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Hi!"}]},
            _create_max_tokens_retry_message(1),
        ]
        assert _get_max_tokens_attempt_count(history) == 1

    def test_get_attempt_count_two_retries(self):
        """Should count [X][X] as 2 attempts."""
        history = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            _create_max_tokens_retry_message(1),
            {"role": "assistant", "content": [{"type": "text", "text": "partial..."}]},
            _create_max_tokens_retry_message(2),
        ]
        # Should find the most recent retry message with [X][X]
        assert _get_max_tokens_attempt_count(history) == 2

    def test_get_attempt_count_three_retries(self):
        """Should count [X][X][X] as 3 attempts."""
        msg = _create_max_tokens_retry_message(3)
        history = [msg]
        assert _get_max_tokens_attempt_count(history) == 3

    def test_create_retry_message_structure(self):
        """Retry message should have correct structure."""
        msg = _create_max_tokens_retry_message(1)

        assert msg["role"] == "user"
        assert isinstance(msg["content"], list)
        assert len(msg["content"]) == 1
        assert msg["content"][0]["type"] == "text"

    def test_create_retry_message_contains_marker(self):
        """Retry message should contain the marker."""
        msg = _create_max_tokens_retry_message(1)
        text = msg["content"][0]["text"]

        assert "[MAX_TOKENS_RETRY]" in text

    def test_create_retry_message_contains_attempt_number(self):
        """Retry message should show attempt number."""
        msg1 = _create_max_tokens_retry_message(1)
        msg2 = _create_max_tokens_retry_message(2)
        msg3 = _create_max_tokens_retry_message(3)

        assert "Attempt 1 of 3" in msg1["content"][0]["text"]
        assert "Attempt 2 of 3" in msg2["content"][0]["text"]
        assert "Attempt 3 of 3" in msg3["content"][0]["text"]

    def test_create_retry_message_x_markers(self):
        """Retry message should have correct number of [X] markers."""
        msg1 = _create_max_tokens_retry_message(1)
        msg2 = _create_max_tokens_retry_message(2)
        msg3 = _create_max_tokens_retry_message(3)

        assert msg1["content"][0]["text"].count("[X]") == 1
        assert msg2["content"][0]["text"].count("[X]") == 2
        assert msg3["content"][0]["text"].count("[X]") == 3

    def test_create_retry_message_contains_instructions(self):
        """Retry message should contain helpful instructions."""
        msg = _create_max_tokens_retry_message(1)
        text = msg["content"][0]["text"]

        assert "cut off" in text.lower() or "max token" in text.lower()
        assert "continue" in text.lower()
        assert "concise" in text.lower()

    def test_get_attempt_count_with_tool_results(self):
        """Should find retry message even with tool results in between."""
        history = [
            {"role": "user", "content": [{"type": "text", "text": "Do something"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "123", "name": "test", "input": {}}
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "123", "content": "done"}
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "partial..."}]},
            _create_max_tokens_retry_message(1),
        ]
        assert _get_max_tokens_attempt_count(history) == 1

    def test_get_attempt_count_string_content(self):
        """Should handle string content (not just list)."""
        history = [
            {"role": "user", "content": "[MAX_TOKENS_RETRY] test [X][X]"},
        ]
        assert _get_max_tokens_attempt_count(history) == 2


class TestMaxTokensRetryFlow:
    """Test the full retry flow simulation."""

    def test_retry_flow_simulation(self):
        """Simulate the max_tokens retry flow from start to max retries."""
        # Initial conversation
        chat_history = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Write a long essay"}],
            },
        ]

        # First max_tokens hit
        assert _get_max_tokens_attempt_count(chat_history) == 0

        # Add partial response and retry message
        chat_history.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Here is my essay..."}],
            }
        )
        chat_history.append(_create_max_tokens_retry_message(1))
        assert _get_max_tokens_attempt_count(chat_history) == 1

        # Second max_tokens hit
        chat_history.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Continuing..."}],
            }
        )
        chat_history.append(_create_max_tokens_retry_message(2))
        assert _get_max_tokens_attempt_count(chat_history) == 2

        # Third max_tokens hit
        chat_history.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Still trying..."}],
            }
        )
        chat_history.append(_create_max_tokens_retry_message(3))
        assert _get_max_tokens_attempt_count(chat_history) == 3

        # At 3 attempts, should stop retrying
        assert _get_max_tokens_attempt_count(chat_history) >= 3
