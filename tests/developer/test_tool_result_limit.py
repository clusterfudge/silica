"""Tests for tool result size limiting."""

from silica.developer.tool_result_limit import (
    estimate_tokens,
    get_result_content_size,
    create_truncation_message,
    check_and_limit_result,
    get_max_tool_result_tokens,
    DEFAULT_MAX_TOOL_RESULT_TOKENS,
)


class TestEstimateTokens:
    """Tests for token estimation."""

    def test_empty_string(self):
        """Empty string should return 0 tokens."""
        assert estimate_tokens("") == 0

    def test_short_string(self):
        """Short strings should estimate a few tokens."""
        # "hello" is 5 chars, ~1-2 tokens
        result = estimate_tokens("hello")
        assert 1 <= result <= 5

    def test_long_string(self):
        """Long strings should estimate proportionally."""
        # 1000 chars should be roughly 250-350 tokens
        text = "a" * 1000
        result = estimate_tokens(text)
        assert 200 <= result <= 400

    def test_realistic_text(self):
        """Realistic text should have reasonable estimates."""
        text = "This is a realistic sentence with some code: def foo(): return 42"
        result = estimate_tokens(text)
        # ~67 chars, should be ~15-25 tokens
        assert 10 <= result <= 30


class TestGetResultContentSize:
    """Tests for getting result content size."""

    def test_string_content(self):
        """String content should be measured."""
        result = {"content": "hello world"}
        tokens, content_type = get_result_content_size(result)
        assert tokens > 0
        assert content_type == "text"

    def test_list_with_text_blocks(self):
        """List content with text blocks."""
        result = {
            "content": [
                {"type": "text", "text": "First paragraph"},
                {"type": "text", "text": "Second paragraph"},
            ]
        }
        tokens, content_type = get_result_content_size(result)
        assert tokens > 0
        assert content_type == "text"

    def test_list_with_image_base64(self):
        """Base64 image data should be measured."""
        # Simulate a small base64 image
        base64_data = "a" * 10000  # 10K chars of base64
        result = {
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "data": base64_data},
                }
            ]
        }
        tokens, content_type = get_result_content_size(result)
        assert tokens > 2000  # Should be significant
        assert "image" in content_type

    def test_mixed_content(self):
        """Mixed content types."""
        result = {
            "content": [
                {"type": "text", "text": "Here is an image:"},
                {
                    "type": "image",
                    "source": {"type": "base64", "data": "abc123"},
                },
            ]
        }
        tokens, content_type = get_result_content_size(result)
        assert tokens > 0
        assert "image" in content_type or "text" in content_type

    def test_empty_content(self):
        """Empty content should return 0."""
        result = {"content": ""}
        tokens, content_type = get_result_content_size(result)
        assert tokens == 0


class TestCreateTruncationMessage:
    """Tests for truncation message creation."""

    def test_text_truncation_message(self):
        """Truncation message for text content."""
        msg = create_truncation_message(
            tool_name="read_file",
            original_tokens=100000,
            max_tokens=50000,
            content_type="text",
        )
        assert "read_file" in msg
        assert "100,000" in msg
        assert "50,000" in msg
        assert "grep" in msg.lower() or "search" in msg.lower()

    def test_image_truncation_message(self):
        """Truncation message for image content."""
        msg = create_truncation_message(
            tool_name="screenshot",
            original_tokens=80000,
            max_tokens=50000,
            content_type="image",
        )
        assert "screenshot" in msg
        assert "image" in msg.lower() or "resolution" in msg.lower()

    def test_mixed_truncation_message(self):
        """Truncation message for mixed content."""
        msg = create_truncation_message(
            tool_name="some_tool",
            original_tokens=75000,
            max_tokens=50000,
            content_type="text+image",
        )
        assert "some_tool" in msg


class TestCheckAndLimitResult:
    """Tests for the main check and limit function."""

    def test_small_result_unchanged(self):
        """Small results should pass through unchanged."""
        result = {
            "type": "tool_result",
            "tool_use_id": "test123",
            "content": "Small result",
        }
        limited, was_truncated, original_tokens = check_and_limit_result(
            result, "test_tool"
        )
        assert not was_truncated
        assert original_tokens == 0
        assert limited["content"] == "Small result"
        # Internal fields should not be in result (would break API)
        assert "_truncated" not in limited
        assert "_original_tokens" not in limited

    def test_large_result_truncated(self):
        """Large results should be truncated."""
        # Create a result that exceeds the limit
        large_content = "x" * 500000  # ~166K tokens
        result = {
            "type": "tool_result",
            "tool_use_id": "test123",
            "content": large_content,
        }
        limited, was_truncated, original_tokens = check_and_limit_result(
            result, "test_tool", max_tokens=10000
        )
        assert was_truncated
        assert original_tokens > 50000  # Original token count returned separately
        assert limited["is_error"] is True
        assert "TOOL RESULT TOO LARGE" in limited["content"]
        assert limited["tool_use_id"] == "test123"  # Preserved
        # Internal fields should NOT be in result (would break API)
        assert "_truncated" not in limited
        assert "_original_tokens" not in limited

    def test_preserves_tool_use_id(self):
        """Tool use ID should be preserved even when truncated."""
        large_content = "x" * 500000
        result = {
            "type": "tool_result",
            "tool_use_id": "my_unique_id",
            "content": large_content,
        }
        limited, _, _ = check_and_limit_result(result, "test", max_tokens=1000)
        assert limited["tool_use_id"] == "my_unique_id"

    def test_custom_max_tokens(self):
        """Custom max_tokens should be respected."""
        content = "x" * 30000  # ~10K tokens
        result = {"content": content}

        # Should pass with high limit
        _, truncated1, _ = check_and_limit_result(result, "test", max_tokens=50000)
        assert not truncated1

        # Should fail with low limit
        _, truncated2, _ = check_and_limit_result(result, "test", max_tokens=5000)
        assert truncated2

    def test_returns_original_token_count(self):
        """Truncated results should return original token count."""
        large_content = "x" * 300000  # ~100K tokens
        result = {"content": large_content}
        limited, was_truncated, original_tokens = check_and_limit_result(
            result, "test", max_tokens=10000
        )
        assert was_truncated
        assert original_tokens > 50000
        # Internal fields should NOT be in result
        assert "_original_tokens" not in limited

    def test_truncated_result_has_only_valid_api_fields(self):
        """Truncated results should only have fields valid for the API schema."""
        large_content = "x" * 500000
        result = {
            "type": "tool_result",
            "tool_use_id": "test123",
            "content": large_content,
        }
        limited, was_truncated, _ = check_and_limit_result(
            result, "test_tool", max_tokens=10000
        )
        assert was_truncated
        # Only these fields are valid in the API schema
        valid_fields = {"type", "tool_use_id", "content", "is_error"}
        for key in limited.keys():
            assert key in valid_fields, f"Unexpected field '{key}' in truncated result"


class TestGetMaxToolResultTokens:
    """Tests for environment variable configuration."""

    def test_default_value(self, monkeypatch):
        """Should return default when env var not set."""
        monkeypatch.delenv("SILICA_MAX_TOOL_RESULT_TOKENS", raising=False)
        assert get_max_tool_result_tokens() == DEFAULT_MAX_TOOL_RESULT_TOKENS

    def test_custom_value(self, monkeypatch):
        """Should use custom value from env var."""
        monkeypatch.setenv("SILICA_MAX_TOOL_RESULT_TOKENS", "75000")
        assert get_max_tool_result_tokens() == 75000

    def test_invalid_value_uses_default(self, monkeypatch, capsys):
        """Invalid env var should fall back to default with warning."""
        monkeypatch.setenv("SILICA_MAX_TOOL_RESULT_TOKENS", "not_a_number")
        result = get_max_tool_result_tokens()
        assert result == DEFAULT_MAX_TOOL_RESULT_TOKENS
        captured = capsys.readouterr()
        assert "Invalid" in captured.out or "Warning" in captured.out

    def test_too_small_value_uses_default(self, monkeypatch, capsys):
        """Value below minimum should fall back to default with warning."""
        monkeypatch.setenv("SILICA_MAX_TOOL_RESULT_TOKENS", "100")
        result = get_max_tool_result_tokens()
        assert result == DEFAULT_MAX_TOOL_RESULT_TOKENS
        captured = capsys.readouterr()
        assert (
            "below minimum" in captured.out.lower() or "warning" in captured.out.lower()
        )


class TestEdgeCases:
    """Tests for edge cases."""

    def test_none_content(self):
        """None content should be handled gracefully."""
        result = {"content": None}
        tokens, content_type = get_result_content_size(result)
        # Should not crash, tokens should be 0 or minimal
        assert tokens >= 0

    def test_empty_list_content(self):
        """Empty list content should return 0 tokens."""
        result = {"content": []}
        tokens, content_type = get_result_content_size(result)
        assert tokens == 0

    def test_nested_unknown_types(self):
        """Unknown nested types should be handled."""
        result = {
            "content": [
                {"type": "unknown_type", "data": "some data"},
                {"type": "another_unknown"},
            ]
        }
        tokens, content_type = get_result_content_size(result)
        # Should estimate based on str representation
        assert tokens >= 0

    def test_list_with_string_items(self):
        """List containing plain strings."""
        result = {"content": ["first string", "second string"]}
        tokens, content_type = get_result_content_size(result)
        assert tokens > 0
        assert content_type == "text"
