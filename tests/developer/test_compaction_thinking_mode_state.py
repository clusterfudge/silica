"""Tests for thinking mode state management during compaction."""

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
def agent_context_with_thinking_enabled(persona_base_dir):
    """Create an agent context with thinking mode enabled."""
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
        ]
    )

    return context


@pytest.fixture
def agent_context_with_ultra_thinking(persona_base_dir):
    """Create an agent context with ultra thinking mode enabled."""
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

    # Enable ultra thinking mode
    context.thinking_mode = "ultra"

    # Add messages with thinking blocks
    context.chat_history.extend(
        [
            {"role": "user", "content": [{"type": "text", "text": "Complex question"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "This requires deep thought..."},
                    {"type": "text", "text": "Detailed response"},
                ],
            },
        ]
    )

    return context


def test_compaction_disables_thinking_mode_when_normal(
    mock_client, agent_context_with_thinking_enabled, tmp_path
):
    """Test that compaction disables thinking mode when it was set to 'normal'."""
    # Verify thinking mode is initially enabled
    assert agent_context_with_thinking_enabled.thinking_mode == "normal"

    # Create compacter
    compacter = ConversationCompacter(client=mock_client)

    # Mock the history directory to use tmp_path
    with patch("silica.developer.context.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        # Perform compaction
        metadata = compacter.compact_conversation(
            agent_context_with_thinking_enabled,
            model="claude-opus-4-5-20251101",
            force=True,
        )

    # Verify compaction occurred
    assert metadata is not None

    # Verify thinking mode was disabled
    assert (
        agent_context_with_thinking_enabled.thinking_mode == "off"
    ), "Thinking mode should be disabled after compaction"


def test_compaction_disables_thinking_mode_when_ultra(
    mock_client, agent_context_with_ultra_thinking, tmp_path
):
    """Test that compaction disables thinking mode when it was set to 'ultra'."""
    # Verify thinking mode is initially enabled
    assert agent_context_with_ultra_thinking.thinking_mode == "ultra"

    # Create compacter
    compacter = ConversationCompacter(client=mock_client)

    # Mock the history directory to use tmp_path
    with patch("silica.developer.context.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        # Perform compaction
        metadata = compacter.compact_conversation(
            agent_context_with_ultra_thinking,
            model="claude-opus-4-5-20251101",
            force=True,
        )

    # Verify compaction occurred
    assert metadata is not None

    # Verify thinking mode was disabled
    assert (
        agent_context_with_ultra_thinking.thinking_mode == "off"
    ), "Thinking mode should be disabled after compaction"


def test_compaction_leaves_thinking_off_when_already_off(
    mock_client, persona_base_dir, tmp_path
):
    """Test that compaction doesn't change thinking mode if it's already off."""
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

    # Thinking mode is off by default
    assert context.thinking_mode == "off"

    # Add messages without thinking blocks
    context.chat_history.extend(
        [
            {"role": "user", "content": [{"type": "text", "text": "Question"}]},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Response"}],
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

    # Verify thinking mode is still off
    assert context.thinking_mode == "off", "Thinking mode should remain off"


def test_compaction_thinking_mode_prevents_api_error(
    mock_client, agent_context_with_thinking_enabled, tmp_path
):
    """Test that disabling thinking mode prevents API validation errors after compaction."""
    # Verify thinking mode is initially enabled
    assert agent_context_with_thinking_enabled.thinking_mode == "normal"

    # Create compacter
    compacter = ConversationCompacter(client=mock_client)

    # Mock the history directory to use tmp_path
    with patch("silica.developer.context.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        # Perform compaction
        metadata = compacter.compact_conversation(
            agent_context_with_thinking_enabled,
            model="claude-opus-4-5-20251101",
            force=True,
        )

    # Verify compaction occurred
    assert metadata is not None

    # Verify the conversation structure is valid for the next API call
    # 1. Thinking mode should be off
    assert agent_context_with_thinking_enabled.thinking_mode == "off"

    # 2. Messages should not contain thinking blocks
    compacted_messages = agent_context_with_thinking_enabled.chat_history
    for message in compacted_messages:
        content = message.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    assert block.get("type") not in ["thinking", "redacted_thinking"]

    # 3. Get the API context that would be used for the next call
    api_context = agent_context_with_thinking_enabled.get_api_context()

    # 4. Verify that the conversation ends with a user message
    # (This is important for subsequent API calls)
    assert len(api_context["messages"]) > 0
    assert api_context["messages"][-1]["role"] == "user"

    # This structure (no thinking blocks + thinking_mode off) should not cause
    # API validation errors on subsequent calls


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
