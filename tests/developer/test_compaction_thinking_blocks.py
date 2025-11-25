"""Tests for compaction with extended thinking blocks."""

import pytest
from unittest.mock import Mock, patch
from anthropic.types import Message, Usage, TextBlock

from silica.developer.context import AgentContext
from silica.developer.compacter import ConversationCompacter
from silica.developer.models import get_model
from silica.developer.sandbox import SandboxMode


@pytest.fixture
def mock_client():
    """Create a mock Anthropic client."""
    client = Mock()

    # Mock the count_tokens method
    count_response = Mock()
    count_response.token_count = 50000  # Over threshold to trigger compaction
    client.messages.count_tokens.return_value = count_response

    # Mock the create method for summary generation
    summary_response = Mock(spec=Message)
    summary_response.content = [
        TextBlock(type="text", text="This is a summary of the conversation.")
    ]
    summary_response.usage = Usage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    summary_response.stop_reason = "end_turn"
    client.messages.create.return_value = summary_response

    return client


@pytest.fixture
def agent_context_with_thinking(persona_base_dir):
    """Create an agent context with thinking blocks in messages."""
    mock_ui = Mock()
    mock_ui.permission_callback = Mock(return_value=True)
    mock_ui.permission_rendering_callback = Mock()

    context = AgentContext.create(
        model_spec=get_model("opus"),
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=mock_ui,
        persona_base_directory=persona_base_dir,
    )

    # Enable thinking mode
    context.thinking_mode = "normal"

    # Add messages with thinking blocks
    context.chat_history.extend(
        [
            {"role": "user", "content": [{"type": "text", "text": "First question"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Let me think about this..."},
                    {"type": "text", "text": "First response"},
                ],
            },
            {"role": "user", "content": [{"type": "text", "text": "Second question"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Hmm, interesting..."},
                    {"type": "text", "text": "Second response"},
                ],
            },
            {"role": "user", "content": [{"type": "text", "text": "Third question"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "This is complex..."},
                    {"type": "text", "text": "Third response"},
                ],
            },
        ]
    )

    return context


def test_compaction_strips_thinking_blocks(
    mock_client, agent_context_with_thinking, tmp_path
):
    """Test that compaction strips all thinking blocks from preserved messages."""
    # Create compacter
    compacter = ConversationCompacter(client=mock_client)

    # Mock the history directory to use tmp_path
    with patch("silica.developer.context.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        # Perform compaction
        metadata = compacter.compact_conversation(
            agent_context_with_thinking, model="claude-opus-4-5-20251101", force=True
        )

    # Verify compaction occurred
    assert metadata is not None

    # Check the compacted messages
    compacted_messages = agent_context_with_thinking.chat_history

    # Verify no thinking blocks remain in any message
    for message in compacted_messages:
        content = message.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    assert block.get("type") not in [
                        "thinking",
                        "redacted_thinking",
                    ], f"Found thinking block in compacted message: {block}"


def test_compaction_preserves_text_content(
    mock_client, agent_context_with_thinking, tmp_path
):
    """Test that compaction preserves text content while stripping thinking blocks."""
    # Create compacter
    compacter = ConversationCompacter(client=mock_client)

    # Mock the history directory to use tmp_path
    with patch("silica.developer.context.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        # Perform compaction
        metadata = compacter.compact_conversation(
            agent_context_with_thinking, model="claude-opus-4-5-20251101", force=True
        )

    # Verify compaction occurred
    assert metadata is not None

    # Check that text content is preserved in the last assistant message
    compacted_messages = agent_context_with_thinking.chat_history

    # Find last assistant message in compacted history
    last_assistant_msg = None
    for message in reversed(compacted_messages):
        if message["role"] == "assistant":
            last_assistant_msg = message
            break

    # If there's an assistant message, verify it has text content
    if last_assistant_msg:
        text_blocks = [
            block
            for block in last_assistant_msg["content"]
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        # Should have text content (thinking stripped, text preserved)
        assert (
            len(text_blocks) > 0
        ), "Text content should be preserved after stripping thinking"


def test_strip_all_thinking_blocks_helper():
    """Test the _strip_all_thinking_blocks helper method directly."""
    # Create a mock client
    client = Mock()
    compacter = ConversationCompacter(client=client)

    # Create test messages with thinking blocks
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "Let me think..."},
                {"type": "text", "text": "Hi there!"},
            ],
        },
        {"role": "user", "content": [{"type": "text", "text": "How are you?"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "redacted_thinking"},
                {"type": "text", "text": "I'm doing well!"},
            ],
        },
    ]

    # Strip thinking blocks
    cleaned = compacter._strip_all_thinking_blocks(messages)

    # Verify structure
    assert len(cleaned) == 4

    # Check first assistant message
    assert cleaned[1]["role"] == "assistant"
    assert len(cleaned[1]["content"]) == 1
    assert cleaned[1]["content"][0]["type"] == "text"
    assert cleaned[1]["content"][0]["text"] == "Hi there!"

    # Check second assistant message
    assert cleaned[3]["role"] == "assistant"
    assert len(cleaned[3]["content"]) == 1
    assert cleaned[3]["content"][0]["type"] == "text"
    assert cleaned[3]["content"][0]["text"] == "I'm doing well!"


def test_compaction_with_no_thinking_blocks(mock_client, persona_base_dir, tmp_path):
    """Test that compaction works correctly with messages that have no thinking blocks."""
    mock_ui = Mock()
    mock_ui.permission_callback = Mock(return_value=True)
    mock_ui.permission_rendering_callback = Mock()

    context = AgentContext.create(
        model_spec=get_model("opus"),
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=mock_ui,
        persona_base_directory=persona_base_dir,
    )

    # Add messages without thinking blocks
    context.chat_history.extend(
        [
            {"role": "user", "content": [{"type": "text", "text": "First question"}]},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "First response"}],
            },
            {"role": "user", "content": [{"type": "text", "text": "Second question"}]},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Second response"}],
            },
        ]
    )

    # Create compacter
    compacter = ConversationCompacter(client=mock_client)

    # Mock the history directory to use tmp_path
    with patch("silica.developer.context.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        # Perform compaction
        metadata = compacter.compact_conversation(
            context, model="claude-opus-4-5-20251101", force=True
        )

    # Verify compaction occurred
    assert metadata is not None

    # Verify messages are still valid
    compacted_messages = context.chat_history
    assert len(compacted_messages) > 0

    # All messages should still be valid
    for message in compacted_messages:
        assert "role" in message
        assert "content" in message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
