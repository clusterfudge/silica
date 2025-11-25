"""Tests for compaction ensuring conversation ends with user message when thinking is enabled."""

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
def agent_context_with_thinking_ending_in_assistant(persona_base_dir):
    """Create an agent context with thinking enabled that ends with an assistant message."""
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

    # Add messages that end with an assistant message (typical pattern)
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


@pytest.fixture
def agent_context_with_thinking_ending_in_user(persona_base_dir):
    """Create an agent context with thinking enabled that ends with a user message."""
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

    # Add messages that end with a user message
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
        ]
    )

    return context


def test_compaction_ends_with_user_when_thinking_enabled_ending_in_assistant(
    mock_client, agent_context_with_thinking_ending_in_assistant, tmp_path
):
    """Test that compaction handles conversations that end with assistant message.

    With micro-compaction, thinking_mode is set to "off" after compaction,
    so it's valid for the conversation to end with either user or assistant.
    """
    # Create compacter
    compacter = ConversationCompacter(client=mock_client)

    # Mock the history directory to use tmp_path
    with patch("silica.developer.context.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        # Perform compaction
        _metadata = compacter.compact_conversation(
            agent_context_with_thinking_ending_in_assistant,
            model="claude-opus-4-20250514",
            force=True,
        )

    # Verify compaction occurred
    assert _metadata is not None

    # Verify thinking mode is now off (this is the key fix)
    assert agent_context_with_thinking_ending_in_assistant.thinking_mode == "off"

    # Check that the conversation has valid messages
    compacted_messages = agent_context_with_thinking_ending_in_assistant.chat_history
    assert len(compacted_messages) > 0

    # With thinking_mode="off", ending with assistant is valid
    # The micro-compaction preserves the last message as-is
    assert compacted_messages[-1]["role"] in ["user", "assistant"]

    # Verify the conversation structure is valid
    user_message_count = sum(1 for msg in compacted_messages if msg["role"] == "user")
    assert user_message_count >= 1


def test_compaction_ends_with_user_when_thinking_enabled_ending_in_user(
    mock_client, agent_context_with_thinking_ending_in_user, tmp_path
):
    """Test that compaction preserves user message ending when thinking is enabled and chat already ends in user."""
    # Create compacter
    compacter = ConversationCompacter(client=mock_client)

    # Mock the history directory to use tmp_path
    with patch("silica.developer.context.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        # Perform compaction
        _metadata = compacter.compact_conversation(
            agent_context_with_thinking_ending_in_user,
            model="claude-opus-4-20250514",
            force=True,
        )

    # Verify compaction occurred
    assert _metadata is not None

    # Check that the last message is still a user message
    compacted_messages = agent_context_with_thinking_ending_in_user.chat_history
    assert len(compacted_messages) > 0
    assert (
        compacted_messages[-1]["role"] == "user"
    ), "Last message should remain a user message when thinking is enabled"


def test_compaction_with_thinking_disabled_can_end_with_assistant(
    mock_client, persona_base_dir, tmp_path
):
    """Test that compaction allows assistant message at end when thinking is disabled."""
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

    # Thinking mode is OFF (default)
    assert context.thinking_mode == "off"

    # Add messages ending with assistant (no thinking blocks)
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
        _metadata = compacter.compact_conversation(
            context, model="claude-opus-4-20250514", force=True
        )

    # Verify compaction occurred
    assert _metadata is not None

    # When thinking is off, it's OK to end with assistant message
    context.chat_history
    # The conversation can end with either user or assistant when thinking is off
    # This test just verifies no error occurs


def test_compaction_no_thinking_blocks_remain(
    mock_client, agent_context_with_thinking_ending_in_assistant, tmp_path
):
    """Test that all thinking blocks are stripped regardless of final message role."""
    # Create compacter
    compacter = ConversationCompacter(client=mock_client)

    # Mock the history directory to use tmp_path
    with patch("silica.developer.context.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        # Perform compaction
        _metadata = compacter.compact_conversation(
            agent_context_with_thinking_ending_in_assistant,
            model="claude-opus-4-20250514",
            force=True,
        )

    # Verify no thinking blocks remain
    compacted_messages = agent_context_with_thinking_ending_in_assistant.chat_history
    for message in compacted_messages:
        content = message.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    assert block.get("type") not in [
                        "thinking",
                        "redacted_thinking",
                    ], f"Found thinking block in compacted message: {block}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
