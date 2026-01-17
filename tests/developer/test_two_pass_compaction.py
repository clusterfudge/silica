"""Tests for two-pass compaction strategy.

Tests the generate_summary_guidance(), generate_summary() with guidance,
_generate_summary_standalone(), and the two-pass decision logic in compact_conversation().
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from silica.developer.compacter import ConversationCompacter, CompactionSummary


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

    def create(self, model, system, messages, max_tokens):
        """Mock create that returns configurable responses."""
        self.create_calls.append(
            {
                "model": model,
                "system": system,
                "messages": messages,
                "max_tokens": max_tokens,
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
    context.history_base_dir = Path("/tmp/test")
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
        "tools": [],
        "messages": context.chat_history,
    }

    return context


class TestGenerateSummaryGuidance:
    """Tests for generate_summary_guidance() method."""

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


class TestGenerateSummaryWithGuidance:
    """Tests for generate_summary() with guidance parameter."""

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


class TestGenerateSummaryStandalone:
    """Tests for _generate_summary_standalone() method."""

    def test_summarizes_raw_messages(self, compacter):
        """Test that standalone summary works with raw messages."""
        compacter.client.responses = ["Standalone summary"]

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]

        summary = compacter._generate_summary_standalone(messages, "haiku")

        assert summary.summary == "Standalone summary"
        assert summary.original_message_count == 2

    def test_includes_guidance_when_provided(self, compacter):
        """Test that guidance is included in standalone summary."""
        compacter.client.responses = ["Guided standalone summary"]

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]

        guidance = "Focus on the greeting"
        summary = compacter._generate_summary_standalone(
            messages, "haiku", guidance=guidance
        )

        assert summary.summary == "Guided standalone summary"

        # Check guidance is in system prompt
        call = compacter.client.messages.create_calls[0]
        assert "Focus on the greeting" in call["system"]

    def test_minimal_system_prompt(self, compacter):
        """Test that standalone uses minimal system prompt (no tools overhead)."""
        compacter.client.responses = ["Summary"]

        messages = [{"role": "user", "content": "Test"}]
        compacter._generate_summary_standalone(messages, "haiku")

        call = compacter.client.messages.create_calls[0]
        # System prompt should be relatively short
        assert len(call["system"]) < 1000


class TestTwoPassDecisionLogic:
    """Tests for the two-pass vs single-pass decision in compact_conversation()."""

    def test_uses_single_pass_when_messages_fit(self, compacter, mock_agent_context):
        """Test that single-pass is used when messages fit in context window."""
        compacter.client.responses = ["Single pass summary"]

        # Create a mock summary to return
        mock_summary = CompactionSummary(
            original_message_count=3,
            original_token_count=1000,
            summary_token_count=100,
            compaction_ratio=0.1,
            summary="Single pass summary",
        )

        # Mock count_tokens to return a small value (fits in context)
        # Mock _generate_summary_standalone since that's what single-pass uses now
        with patch.object(compacter, "should_compact", return_value=True):
            with patch.object(
                compacter, "count_tokens", return_value=50000
            ):  # Well under 190k
                with patch.object(
                    compacter, "_generate_summary_standalone", return_value=mock_summary
                ) as mock_standalone:
                    with patch.object(
                        compacter, "generate_summary_guidance"
                    ) as mock_guidance:
                        with patch.object(
                            compacter,
                            "_archive_and_rotate",
                            return_value="archive.json",
                        ):
                            compacter.compact_conversation(
                                mock_agent_context, "haiku", turns=2, force=True
                            )

        # Single-pass should call _generate_summary_standalone (not guidance)
        assert mock_standalone.called
        # generate_summary_guidance should NOT have been called for single-pass
        assert not mock_guidance.called

    def test_uses_two_pass_when_messages_exceed_limit(
        self, compacter, mock_agent_context
    ):
        """Test that two-pass is used when messages exceed context window."""
        # Set up a larger conversation
        mock_agent_context.chat_history = [
            {"role": "user", "content": f"Message {i}"} for i in range(20)
        ]
        mock_agent_context.get_api_context.return_value = {
            "system": [{"type": "text", "text": "System prompt"}],
            "tools": [],
            "messages": mock_agent_context.chat_history,
        }

        compacter.client.responses = [
            "Guidance for summarization",  # Pass 1 response
            "Two pass summary",  # Pass 2 response
        ]

        # Mock count_tokens to return high value (exceeds limit)
        with patch.object(compacter, "should_compact", return_value=True):
            with patch.object(
                compacter, "count_tokens", return_value=250000
            ):  # Exceeds 190k
                with patch.object(
                    compacter, "_archive_and_rotate", return_value="archive.json"
                ):
                    compacter.compact_conversation(
                        mock_agent_context, "haiku", turns=5, force=True
                    )

        # Should have two create calls (guidance + summary)
        create_calls = compacter.client.messages.create_calls
        assert len(create_calls) == 2


class TestErrorHandling:
    """Tests for error handling in two-pass compaction."""

    def test_falls_back_when_guidance_fails(self, compacter, mock_agent_context):
        """Test that summarization proceeds even if guidance generation fails."""
        # Set up conversation
        mock_agent_context.chat_history = [
            {"role": "user", "content": f"Message {i}"} for i in range(10)
        ]
        mock_agent_context.get_api_context.return_value = {
            "system": [{"type": "text", "text": "System prompt"}],
            "tools": [],
            "messages": mock_agent_context.chat_history,
        }

        # Make guidance generation fail, but summary succeed
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

        # Mock count_tokens to return high value (trigger two-pass)
        with patch.object(compacter, "should_compact", return_value=True):
            with patch.object(compacter, "count_tokens", return_value=250000):
                with patch.object(
                    compacter, "_archive_and_rotate", return_value="archive.json"
                ):
                    # Should not raise, should proceed with empty guidance
                    compacter.compact_conversation(
                        mock_agent_context, "haiku", turns=3, force=True
                    )

        # The summary should still be generated (call_count should be 2: failed guidance + summary)
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
