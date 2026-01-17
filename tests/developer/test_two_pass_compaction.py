"""Tests for two-pass compaction strategy.

Tests the generate_summary_guidance(), _generate_summary_with_context(),
and the two-pass compaction flow in compact_conversation().
"""

import pytest
from unittest.mock import MagicMock, patch

from silica.developer.compacter import ConversationCompacter


class MockMessagesClient:
    """Mock for the Anthropic messages client."""

    def __init__(self, parent):
        self.parent = parent
        self.create_calls = []
        self.count_tokens_calls = []

    def count_tokens(self, model, system=None, messages=None, tools=None):
        """Mock count_tokens that returns configurable token counts."""
        self.count_tokens_calls.append(
            {
                "model": model,
                "system": system,
                "messages": messages,
                "tools": tools,
            }
        )

        # Return the configured token count or estimate from content
        if self.parent.token_count is not None:
            count = self.parent.token_count
        else:
            # Estimate from content
            total_chars = 0
            if system:
                for block in system:
                    if isinstance(block, dict) and block.get("type") == "text":
                        total_chars += len(block.get("text", ""))
            if messages:
                for msg in messages:
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        total_chars += len(content)
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and "text" in block:
                                total_chars += len(block["text"])
            count = max(1, total_chars // 4)

        class TokenResponse:
            def __init__(self, token_count):
                self.token_count = token_count

        return TokenResponse(count)

    def create(self, model, system, messages, max_tokens, tools=None, tool_choice=None):
        """Mock create that returns configurable responses."""
        self.create_calls.append(
            {
                "model": model,
                "system": system,
                "messages": messages,
                "max_tokens": max_tokens,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )

        # Get the appropriate response
        response_text = self.parent.get_next_response()

        class ContentItem:
            def __init__(self, text):
                self.text = text
                self.type = "text"

        class Usage:
            input_tokens = 100
            output_tokens = 50

        class MessageResponse:
            def __init__(self, content_text):
                self.content = [ContentItem(content_text)]
                self.usage = Usage()
                self.stop_reason = "end_turn"

        return MessageResponse(response_text)


class MockAnthropicClient:
    """Mock Anthropic client for testing."""

    def __init__(self, responses=None, token_count=None):
        """Initialize mock client.

        Args:
            responses: List of response strings to return in order
            token_count: Fixed token count to return (None = estimate)
        """
        self.responses = responses or ["Mock summary response"]
        self.response_index = 0
        self.token_count = token_count
        self.messages = MockMessagesClient(self)

    def get_next_response(self):
        """Get the next response in the queue."""
        if self.response_index < len(self.responses):
            response = self.responses[self.response_index]
            self.response_index += 1
            return response
        return self.responses[-1] if self.responses else "Default response"


@pytest.fixture
def mock_client():
    """Create a mock Anthropic client."""
    return MockAnthropicClient()


@pytest.fixture
def compacter(mock_client):
    """Create a ConversationCompacter with mock client."""
    return ConversationCompacter(client=mock_client)


@pytest.fixture
def mock_agent_context():
    """Create a mock agent context."""
    context = MagicMock()
    context.parent_session_id = "parent-123"
    context.session_id = "session-456"
    context.model_spec = {"title": "claude-sonnet-4-20250514", "context_window": 200000}
    context.sandbox = MagicMock()
    context.user_interface = MagicMock()
    context.usage = MagicMock()
    context.memory_manager = None
    context.history_base_dir = None
    context.thinking_mode = "off"
    context.chat_history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
        {"role": "assistant", "content": "I'm doing well, thanks!"},
        {"role": "user", "content": "Great!"},
    ]

    # Mock get_api_context
    context.get_api_context.return_value = {
        "system": [{"type": "text", "text": "You are a helpful assistant."}],
        "tools": [{"name": "test_tool", "description": "A test tool"}],
        "messages": context.chat_history,
    }

    return context


class TestGenerateSummaryGuidance:
    """Tests for generate_summary_guidance() method (Pass 1)."""

    def test_generates_guidance_successfully(self, compacter, mock_agent_context):
        """Test that guidance is generated from conversation context."""
        compacter.client.responses = [
            "Key points to preserve:\n1. User greeted\n2. Assistant responded"
        ]

        guidance = compacter.generate_summary_guidance(
            mock_agent_context, "haiku", messages_to_compact_count=3
        )

        assert "Key points to preserve" in guidance
        assert len(compacter.client.messages.create_calls) == 1

        # Check that the guidance request was appended to messages
        call = compacter.client.messages.create_calls[0]
        last_message = call["messages"][-1]
        assert "compact" in last_message["content"].lower()
        assert "3" in last_message["content"]  # messages_to_compact_count

    def test_includes_system_and_tools_for_cache(self, compacter, mock_agent_context):
        """Test that guidance request includes system and tools for cache efficiency."""
        compacter.client.responses = ["Guidance output"]

        compacter.generate_summary_guidance(
            mock_agent_context, "haiku", messages_to_compact_count=3
        )

        call = compacter.client.messages.create_calls[0]
        # Should include system prompt and tools for cache efficiency
        assert call["system"] is not None
        assert call["tools"] is not None

    def test_returns_empty_on_error(self, compacter, mock_agent_context):
        """Test that empty string is returned when guidance generation fails."""
        # Make the client raise an exception
        compacter.client.messages.create = MagicMock(side_effect=Exception("API error"))

        guidance = compacter.generate_summary_guidance(
            mock_agent_context, "haiku", messages_to_compact_count=3
        )

        assert guidance == ""

    def test_uses_full_conversation_context(self, compacter, mock_agent_context):
        """Test that guidance uses the full conversation context."""
        compacter.client.responses = ["Guidance output"]

        compacter.generate_summary_guidance(
            mock_agent_context, "haiku", messages_to_compact_count=3
        )

        call = compacter.client.messages.create_calls[0]
        # Should have original messages + guidance request
        assert len(call["messages"]) == len(mock_agent_context.chat_history) + 1


class TestGenerateSummaryWithContext:
    """Tests for _generate_summary_with_context() method (Pass 2)."""

    def test_uses_same_system_and_tools(self, compacter, mock_agent_context):
        """Test that Pass 2 uses same system/tools as original context."""
        compacter.client.responses = ["Summary with context"]

        messages_to_summarize = mock_agent_context.chat_history[:3]
        guidance = "Focus on the greeting"

        compacter._generate_summary_with_context(
            mock_agent_context, messages_to_summarize, "haiku", guidance
        )

        call = compacter.client.messages.create_calls[0]
        # Should use the same system and tools from original context
        assert call["system"] == mock_agent_context.get_api_context()["system"]
        assert call["tools"] == mock_agent_context.get_api_context()["tools"]

    def test_uses_message_prefix_plus_request(self, compacter, mock_agent_context):
        """Test that Pass 2 uses message prefix + summary request."""
        compacter.client.responses = ["Summary"]

        # Use 2 messages (ends with assistant) so we don't drop any
        messages_to_summarize = mock_agent_context.chat_history[:2]
        guidance = "Focus on the greeting"

        compacter._generate_summary_with_context(
            mock_agent_context, messages_to_summarize, "haiku", guidance
        )

        call = compacter.client.messages.create_calls[0]
        # Should have prefix messages + summary request
        # Prefix ends with assistant, so no messages dropped
        assert len(call["messages"]) == len(messages_to_summarize) + 1
        # Last message should contain guidance
        assert "Summary Guidance" in call["messages"][-1]["content"]

    def test_includes_guidance_in_request(self, compacter, mock_agent_context):
        """Test that guidance is included in the summary request."""
        compacter.client.responses = ["Summary with guidance"]

        messages_to_summarize = mock_agent_context.chat_history[:3]
        guidance = "Important: preserve the greeting context"

        compacter._generate_summary_with_context(
            mock_agent_context, messages_to_summarize, "haiku", guidance
        )

        call = compacter.client.messages.create_calls[0]
        last_message = call["messages"][-1]["content"]
        assert "Important: preserve the greeting context" in last_message


class TestGenerateSummaryWithGuidance:
    """Tests for generate_summary() with guidance parameter (legacy support)."""

    def test_incorporates_guidance_into_prompt(self, compacter, mock_agent_context):
        """Test that guidance is incorporated into the system prompt."""
        compacter.client.responses = ["Summary with guidance applied"]

        guidance = "Focus on: user greeting, assistant response quality"
        summary = compacter.generate_summary(
            mock_agent_context, "haiku", guidance=guidance
        )

        assert summary.summary == "Summary with guidance applied"

        # Check that guidance appears in system prompt
        call = compacter.client.messages.create_calls[0]
        assert "Focus on:" in call["system"] or "Summary Guidance" in call["system"]

    def test_works_without_guidance(self, compacter, mock_agent_context):
        """Test that generate_summary works without guidance (backward compatible)."""
        compacter.client.responses = ["Summary without guidance"]

        summary = compacter.generate_summary(mock_agent_context, "haiku")

        assert summary.summary == "Summary without guidance"
        assert len(compacter.client.messages.create_calls) == 1


class TestTwoPassCompaction:
    """Tests for two-pass compaction flow."""

    def test_always_uses_two_passes(self, compacter, mock_agent_context):
        """Test that compaction always uses two passes (guidance + summary)."""
        compacter.client.responses = [
            "Guidance for summarization",  # Pass 1 response
            "Summary with guidance",  # Pass 2 response
        ]

        with patch.object(compacter, "should_compact", return_value=True):
            with patch.object(
                compacter, "_archive_and_rotate", return_value="archive.json"
            ):
                compacter.compact_conversation(
                    mock_agent_context, "haiku", turns=2, force=True
                )

        # Should have two create calls (guidance + summary)
        create_calls = compacter.client.messages.create_calls
        assert len(create_calls) == 2

    def test_both_passes_use_same_system_and_tools(self, compacter, mock_agent_context):
        """Test that both passes use same system/tools for cache efficiency."""
        compacter.client.responses = [
            "Guidance",
            "Summary",
        ]

        with patch.object(compacter, "should_compact", return_value=True):
            with patch.object(
                compacter, "_archive_and_rotate", return_value="archive.json"
            ):
                compacter.compact_conversation(
                    mock_agent_context, "haiku", turns=2, force=True
                )

        create_calls = compacter.client.messages.create_calls
        pass1_call = create_calls[0]
        pass2_call = create_calls[1]

        # Both passes should have same system and tools
        assert pass1_call["system"] == pass2_call["system"]
        assert pass1_call["tools"] == pass2_call["tools"]

    def test_pass2_uses_message_prefix(self, compacter, mock_agent_context):
        """Test that Pass 2 uses only the messages to be compacted."""
        compacter.client.responses = [
            "Guidance",
            "Summary",
        ]

        with patch.object(compacter, "should_compact", return_value=True):
            with patch.object(
                compacter, "_archive_and_rotate", return_value="archive.json"
            ):
                compacter.compact_conversation(
                    mock_agent_context, "haiku", turns=2, force=True
                )

        create_calls = compacter.client.messages.create_calls
        pass1_call = create_calls[0]
        pass2_call = create_calls[1]

        # Pass 1 should have more messages (full context + guidance request)
        # Pass 2 should have fewer (just prefix + summary request)
        assert len(pass1_call["messages"]) > len(pass2_call["messages"])


class TestErrorHandling:
    """Tests for error handling in two-pass compaction."""

    def test_proceeds_when_guidance_fails(self, compacter, mock_agent_context):
        """Test that summarization proceeds with empty guidance on Pass 1 failure."""
        call_count = [0]

        def mock_create(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call (guidance) fails
                raise Exception("Guidance generation failed")
            else:
                # Second call (summary) succeeds
                class ContentItem:
                    def __init__(self):
                        self.text = "Summary without guidance"
                        self.type = "text"

                class Usage:
                    input_tokens = 100
                    output_tokens = 50

                class Response:
                    content = [ContentItem()]
                    usage = Usage()
                    stop_reason = "end_turn"

                return Response()

        compacter.client.messages.create = mock_create

        with patch.object(compacter, "should_compact", return_value=True):
            with patch.object(
                compacter, "_archive_and_rotate", return_value="archive.json"
            ):
                # Should not raise, should proceed with empty guidance
                compacter.compact_conversation(
                    mock_agent_context, "haiku", turns=2, force=True
                )

        # Both calls should have been attempted
        assert call_count[0] == 2

    def test_generate_summary_guidance_handles_exception(
        self, compacter, mock_agent_context
    ):
        """Test that generate_summary_guidance returns empty string on exception."""
        compacter.client.messages.create = MagicMock(
            side_effect=Exception("Network error")
        )

        result = compacter.generate_summary_guidance(
            mock_agent_context, "haiku", messages_to_compact_count=5
        )

        assert result == ""
