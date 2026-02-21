"""Tests for stripping internal metadata keys from messages during compaction.

Regression test for a bug where the compacter sent raw in-memory chat_history
messages (containing internal keys like 'anthropic_id', 'request_id') to the
Anthropic API.  The API rejects unknown top-level message fields, causing
compaction to fail with:

    messages.N.anthropic_id: Extra inputs are not permitted

The fix ensures that _generate_summary_with_context (Pass 2 of two-pass
compaction) strips these internal keys before making API calls.
"""

import pytest
from unittest.mock import MagicMock, patch

from silica.developer.compacter import ConversationCompacter

# Import shared test fixtures
from tests.developer.conftest import MockAnthropicClient


@pytest.fixture
def mock_client():
    """Create a mock Anthropic client."""
    return MockAnthropicClient()


@pytest.fixture
def compacter(mock_client):
    """Create a ConversationCompacter with mock client."""
    return ConversationCompacter(client=mock_client)


def _make_chat_history_with_internal_keys():
    """Create a chat history that mimics what the agent loop produces in memory.

    The agent loop adds 'anthropic_id' and 'request_id' to assistant messages
    for provenance tracking.  Content blocks may also carry extra keys like
    'citations' and 'caller' that the SDK adds to responses.
    """
    return [
        {"role": "user", "content": "Hello, can you help me?"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "Of course! How can I help?",
                    "citations": None,  # SDK adds this
                }
            ],
            "anthropic_id": "msg_01ABC123",  # agent_loop adds this
            "request_id": "req_01XYZ789",  # agent_loop adds this
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_01DEF456",
                    "content": "file contents here",
                }
            ],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_01GHI789",
                    "name": "shell_execute",
                    "input": {"command": "ls"},
                    "caller": {"type": "direct"},  # SDK adds this
                },
                {
                    "type": "text",
                    "text": "Let me check that.",
                    "citations": None,
                },
            ],
            "anthropic_id": "msg_02DEF456",
            "request_id": "req_02ABC123",
        },
        {"role": "user", "content": "Thanks for checking!"},
    ]


@pytest.fixture
def mock_agent_context():
    """Create a mock agent context with internal keys in chat_history."""
    context = MagicMock()
    context.parent_session_id = "parent-123"
    context.session_id = "session-456"
    context.model_spec = {"title": "claude-sonnet-4-20250514", "context_window": 200000}
    context.thinking_mode = "off"

    chat_history = _make_chat_history_with_internal_keys()
    context.chat_history = chat_history

    # get_api_context returns CLEAN messages (as it does in production via
    # _process_file_mentions which strips internal keys)
    clean_messages = []
    for msg in chat_history:
        clean = {k: v for k, v in msg.items() if k not in {"anthropic_id", "request_id", "msg_id", "prev_msg_id", "timestamp"}}
        clean_messages.append(clean)

    context.get_api_context.return_value = {
        "system": [{"type": "text", "text": "You are a helpful assistant."}],
        "tools": [{"name": "test_tool", "description": "A test tool"}],
        "messages": clean_messages,
    }

    return context


class TestStripInternalMessageKeys:
    """Tests for _strip_internal_message_keys static method."""

    def test_strips_anthropic_id(self, compacter):
        """Verify anthropic_id is removed from messages."""
        messages = [
            {"role": "assistant", "content": "Hello", "anthropic_id": "msg_123"}
        ]
        cleaned = compacter._strip_internal_message_keys(messages)
        assert "anthropic_id" not in cleaned[0]

    def test_strips_request_id(self, compacter):
        """Verify request_id is removed from messages."""
        messages = [
            {"role": "assistant", "content": "Hello", "request_id": "req_123"}
        ]
        cleaned = compacter._strip_internal_message_keys(messages)
        assert "request_id" not in cleaned[0]

    def test_strips_all_internal_keys(self, compacter):
        """Verify all known internal keys are removed."""
        messages = [
            {
                "role": "assistant",
                "content": "Hello",
                "anthropic_id": "msg_123",
                "request_id": "req_456",
                "msg_id": "id_789",
                "prev_msg_id": "id_000",
                "timestamp": "2026-02-20T00:00:00Z",
            }
        ]
        cleaned = compacter._strip_internal_message_keys(messages)
        assert set(cleaned[0].keys()) == {"role", "content"}

    def test_preserves_role_and_content(self, compacter):
        """Verify role and content are preserved."""
        messages = [
            {
                "role": "assistant",
                "content": "Hello world",
                "anthropic_id": "msg_123",
            }
        ]
        cleaned = compacter._strip_internal_message_keys(messages)
        assert cleaned[0]["role"] == "assistant"
        assert cleaned[0]["content"] == "Hello world"

    def test_strips_citations_from_content_blocks(self, compacter):
        """Verify citations field is stripped from text content blocks."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Hello", "citations": None},
                ],
            }
        ]
        cleaned = compacter._strip_internal_message_keys(messages)
        assert "citations" not in cleaned[0]["content"][0]
        assert cleaned[0]["content"][0]["text"] == "Hello"

    def test_strips_caller_from_tool_use_blocks(self, compacter):
        """Verify caller field is stripped from tool_use content blocks."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "test_tool",
                        "input": {"arg": "val"},
                        "caller": {"type": "direct"},
                    },
                ],
            }
        ]
        cleaned = compacter._strip_internal_message_keys(messages)
        block = cleaned[0]["content"][0]
        assert "caller" not in block
        assert block["id"] == "toolu_123"
        assert block["name"] == "test_tool"
        assert block["input"] == {"arg": "val"}

    def test_preserves_tool_result_blocks(self, compacter):
        """Verify tool_result content blocks are preserved correctly."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "result text",
                    }
                ],
            }
        ]
        cleaned = compacter._strip_internal_message_keys(messages)
        block = cleaned[0]["content"][0]
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "toolu_123"
        assert block["content"] == "result text"

    def test_does_not_mutate_original(self, compacter):
        """Verify the original messages are not modified."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Hello", "citations": None},
                ],
                "anthropic_id": "msg_123",
            }
        ]
        compacter._strip_internal_message_keys(messages)
        # Original should still have anthropic_id and citations
        assert "anthropic_id" in messages[0]
        assert "citations" in messages[0]["content"][0]

    def test_handles_string_content(self, compacter):
        """Verify messages with string content are handled correctly."""
        messages = [
            {"role": "user", "content": "Hello", "anthropic_id": "msg_123"}
        ]
        cleaned = compacter._strip_internal_message_keys(messages)
        assert cleaned[0]["content"] == "Hello"
        assert "anthropic_id" not in cleaned[0]

    def test_handles_empty_messages(self, compacter):
        """Verify empty message list is handled."""
        cleaned = compacter._strip_internal_message_keys([])
        assert cleaned == []


class TestCompactionWithInternalKeys:
    """Integration tests verifying compaction works with internal keys present."""

    def test_pass2_strips_internal_keys_before_api_call(
        self, compacter, mock_agent_context
    ):
        """Verify that _generate_summary_with_context strips internal keys.

        This is the core regression test: the in-memory chat_history has
        'anthropic_id' on assistant messages, but the API must not see them.
        """
        compacter.client.responses = ["Summary text"]
        compacter.client.response_index = 0

        # Use raw messages WITH internal keys (as compact_conversation does)
        raw_messages = mock_agent_context.chat_history[:4]

        # Confirm the raw messages DO have internal keys
        assert any("anthropic_id" in msg for msg in raw_messages), \
            "Test setup: raw messages should have anthropic_id"

        compacter._generate_summary_with_context(
            mock_agent_context, raw_messages, "haiku", "test guidance"
        )

        # Verify the API was called with clean messages
        call = compacter.client.messages.create_calls[0]
        for msg in call["messages"]:
            assert "anthropic_id" not in msg, \
                f"anthropic_id leaked to API in message: {msg.get('role')}"
            assert "request_id" not in msg, \
                f"request_id leaked to API in message: {msg.get('role')}"

    def test_pass2_strips_citations_and_caller_from_blocks(
        self, compacter, mock_agent_context
    ):
        """Verify content block extra keys are also stripped."""
        compacter.client.responses = ["Summary text"]
        compacter.client.response_index = 0

        raw_messages = mock_agent_context.chat_history[:4]
        compacter._generate_summary_with_context(
            mock_agent_context, raw_messages, "haiku", "test guidance"
        )

        call = compacter.client.messages.create_calls[0]
        for msg in call["messages"]:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        assert "citations" not in block, \
                            f"citations leaked to API in block: {block.get('type')}"
                        assert "caller" not in block, \
                            f"caller leaked to API in block: {block.get('type')}"

    def test_full_compact_conversation_with_internal_keys(
        self, compacter, mock_agent_context
    ):
        """End-to-end test: compact_conversation with internal keys in history."""
        compacter.client.responses = [
            "Guidance: preserve the tool interactions",  # Pass 1
            "Summary of conversation",  # Pass 2
        ]
        compacter.client.response_index = 0

        with patch.object(compacter, "should_compact", return_value=True):
            with patch.object(
                compacter, "_archive_and_rotate", return_value="archive.json"
            ):
                metadata = compacter.compact_conversation(
                    mock_agent_context, "haiku", turns=2, force=True
                )

        assert metadata is not None

        # Both API calls should have clean messages
        for i, call in enumerate(compacter.client.messages.create_calls):
            for j, msg in enumerate(call["messages"]):
                assert "anthropic_id" not in msg, \
                    f"Pass {i+1}, message {j}: anthropic_id leaked to API"
                assert "request_id" not in msg, \
                    f"Pass {i+1}, message {j}: request_id leaked to API"
