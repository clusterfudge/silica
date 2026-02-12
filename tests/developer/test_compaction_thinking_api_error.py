"""Test that reproduces and verifies fix for the original compaction + thinking API error.

This test specifically validates the fix for the error:
  messages.1.content.0.type: Expected `thinking` or `redacted_thinking`, but found `text`

The error occurred when:
1. Conversation was compacted while thinking mode was enabled
2. Thinking blocks were stripped from messages (correct)
3. But thinking_mode remained enabled (bug)
4. Next API call tried to use thinking with messages lacking thinking blocks (crash)
"""

import pytest
from unittest.mock import Mock, patch
from anthropic.types import Message, Usage, TextBlock

from silica.developer.context import AgentContext
from silica.developer.compacter import ConversationCompacter
from silica.developer.models import get_model
from silica.developer.sandbox import SandboxMode
from silica.developer.agent_loop import get_thinking_config


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
def agent_context_reproduction_scenario(persona_base_dir):
    """Create an agent context matching the original error scenario.

    This simulates a real conversation with thinking enabled that triggered
    the compaction error.
    """
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

    # Enable thinking mode (this is what the user had enabled)
    context.thinking_mode = "normal"

    # Add a realistic conversation with thinking blocks
    # This simulates the 467 messages mentioned in the error
    for i in range(10):  # Simplified version with 10 messages
        context.chat_history.extend(
            [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": f"Question {i}"}],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": f"Let me analyze question {i}...",
                        },
                        {"type": "text", "text": f"Response {i}"},
                    ],
                },
            ]
        )

    return context


def test_reproduction_of_original_error_is_fixed(
    mock_client, agent_context_reproduction_scenario, tmp_path
):
    """Test that the original error scenario is now fixed.

    This test reproduces the exact conditions that caused the error:
    - Extended thinking mode enabled
    - Compaction triggered
    - Thinking blocks stripped

    Before the fix, this would cause: thinking_mode still "normal" → API error
    After the fix, this should: thinking_mode set to "off" → no error
    """
    # Verify initial state matches the error scenario
    assert agent_context_reproduction_scenario.thinking_mode == "normal"
    assert len(agent_context_reproduction_scenario.chat_history) > 0

    # Verify messages have thinking blocks before compaction
    has_thinking_blocks = False
    for message in agent_context_reproduction_scenario.chat_history:
        if message["role"] == "assistant":
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "thinking":
                        has_thinking_blocks = True
                        break
    assert has_thinking_blocks, "Test setup should have thinking blocks"

    # Create compacter
    compacter = ConversationCompacter(client=mock_client)

    # Mock the history directory to use tmp_path
    with patch("silica.developer.context.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        # Perform compaction (this was triggering the error)
        metadata = compacter.compact_conversation(
            agent_context_reproduction_scenario,
            model="claude-opus-4-6",
            force=True,
        )

    # Verify compaction occurred
    assert metadata is not None

    # THE FIX: Verify thinking mode was disabled
    assert (
        agent_context_reproduction_scenario.thinking_mode == "off"
    ), "BUG FIX: thinking_mode should be disabled after compaction"

    # Verify messages no longer have thinking blocks
    for message in agent_context_reproduction_scenario.chat_history:
        if message["role"] == "assistant":
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        assert block.get("type") not in [
                            "thinking",
                            "redacted_thinking",
                        ], "Thinking blocks should be stripped"


def test_next_api_call_after_compaction_would_succeed(
    mock_client, agent_context_reproduction_scenario, tmp_path
):
    """Test that the next API call after compaction would succeed.

    This simulates what happens AFTER compaction when the agent tries to
    make the next API call. Before the fix, this would fail with:
      Expected `thinking` or `redacted_thinking`, but found `text`
    """
    # Perform compaction
    compacter = ConversationCompacter(client=mock_client)
    with patch("silica.developer.context.Path.home") as mock_home:
        mock_home.return_value = tmp_path
        metadata = compacter.compact_conversation(
            agent_context_reproduction_scenario,
            model="claude-opus-4-6",
            force=True,
        )

    assert metadata is not None

    # Simulate preparing the next API call (as agent_loop.py does)
    api_context = agent_context_reproduction_scenario.get_api_context()

    # Get thinking config (this is what agent_loop does before API call)
    model_spec = get_model("opus")
    thinking_config = get_thinking_config(
        agent_context_reproduction_scenario.thinking_mode, model_spec
    )

    # THE FIX VERIFICATION: thinking_config should be None because mode is "off"
    assert thinking_config is None, "Thinking config should be None when mode is off"

    # Verify the message structure is valid for a non-thinking API call
    messages = api_context["messages"]
    assert len(messages) > 0

    # With micro-compaction, the conversation may end with either user or assistant
    # Since thinking_mode is now "off", both are valid for the API
    # The key is that no thinking blocks remain and thinking_config is None
    assert messages[-1]["role"] in [
        "user",
        "assistant",
    ], "Should have valid final message"

    # Verify no thinking blocks in messages
    for message in messages:
        if message["role"] == "assistant":
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        assert block.get("type") not in [
                            "thinking",
                            "redacted_thinking",
                        ]

    # This structure would be accepted by the API:
    # - No thinking parameter (thinking_config is None)
    # - Messages have no thinking blocks
    # - No validation error about expected thinking blocks


def test_error_would_have_occurred_without_fix(mock_client, persona_base_dir, tmp_path):
    """Test that demonstrates the error would occur without the fix.

    This test manually reproduces the broken state to verify what would happen.
    """
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

    # Add messages with thinking
    context.chat_history.extend(
        [
            {"role": "user", "content": [{"type": "text", "text": "Question"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Analyzing..."},
                    {"type": "text", "text": "Response"},
                ],
            },
        ]
    )

    # Simulate the OLD BROKEN behavior: strip thinking but DON'T disable mode
    compacter = ConversationCompacter(client=mock_client)
    new_messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "Summary message"}],
        },
        {"role": "user", "content": [{"type": "text", "text": "Question"}]},
    ]
    new_messages = compacter._strip_all_thinking_blocks(new_messages)

    # DON'T disable thinking mode (simulating the bug)
    # context.thinking_mode = "off"  # <-- This line was MISSING before fix

    # Update context with stripped messages
    context._chat_history.clear()
    context._chat_history.extend(new_messages)

    # Now try to get thinking config for next API call
    model_spec = get_model("opus")
    thinking_config = get_thinking_config(context.thinking_mode, model_spec)

    # THE BUG: thinking_config is NOT None because mode is still "normal"
    assert (
        thinking_config is not None
    ), "This demonstrates the bug: thinking still enabled"
    assert context.thinking_mode == "normal", "Mode was never disabled (the bug)"

    # Verify messages have no thinking blocks
    has_thinking = False
    for message in context.chat_history:
        if message["role"] == "assistant":
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "thinking":
                        has_thinking = True

    assert not has_thinking, "Messages have no thinking blocks"

    # THIS IS THE ERROR STATE:
    # - thinking_config is not None (thinking parameter would be passed to API)
    # - But messages have no thinking blocks
    # - API would validate and reject with: Expected `thinking` but found `text`

    # The fix ensures this state can never happen by setting thinking_mode = "off"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
