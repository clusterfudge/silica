"""Tests for the /info command."""

import pytest
from unittest.mock import Mock
from pathlib import Path
import json

from silica.developer.context import AgentContext
from silica.developer.toolbox import Toolbox
from silica.developer.sandbox import Sandbox, SandboxMode
from anthropic.types import Usage


@pytest.fixture
def mock_context():
    """Create a mock agent context for testing."""
    context = Mock(spec=AgentContext)

    # Session information
    context.session_id = "12345678-1234-1234-1234-123456789012"
    context.parent_session_id = None
    context.history_base_dir = None  # Will be set by tests that need it

    # Model specification
    context.model_spec = {
        "title": "claude-3-5-sonnet-20241022",
        "max_tokens": 8192,
        "context_window": 200000,
        "pricing": {"input": 3.0, "output": 15.0},
        "cache_pricing": {"read": 0.3, "write": 3.75},
        "thinking_pricing": {"thinking": 9.0},
    }

    # Thinking mode
    context.thinking_mode = "normal"

    # Chat history
    context.chat_history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
        {"role": "assistant", "content": "I'm doing well, thanks!"},
    ]

    # Usage data
    context.usage = [
        (
            Usage(
                input_tokens=100,
                output_tokens=50,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=20,
            ),
            context.model_spec,
        )
    ]

    # Mock usage_summary method
    context.usage_summary.return_value = {
        "total_input_tokens": 100,
        "total_output_tokens": 50,
        "total_thinking_tokens": 0,
        "total_cost": 0.001050,
        "thinking_cost": 0.0,
        "cached_tokens": 20,
        "model_breakdown": {
            "claude-3-5-sonnet-20241022": {
                "total_input_tokens": 100,
                "total_output_tokens": 50,
                "total_thinking_tokens": 0,
                "total_cost": 0.001050,
                "thinking_cost": 0.0,
                "cached_tokens": 20,
            }
        },
    }

    # Optional conversation size
    context._last_conversation_size = 1500

    # Mock sandbox
    context.sandbox = Mock(spec=Sandbox)
    context.sandbox.mode = SandboxMode.ALLOW_ALL

    # Mock user interface
    context.user_interface = Mock()

    return context


def test_info_command_basic(mock_context):
    """Test that the info command generates output without errors."""
    toolbox = Toolbox(mock_context)

    result = toolbox._info(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    # Check that result is a non-empty string
    assert isinstance(result, str)
    assert len(result) > 0

    # Check for key sections
    assert "Session Information" in result
    assert "Model Configuration" in result
    assert "Conversation Statistics" in result
    assert "Token Usage" in result
    assert "Cost Information" in result


def test_info_command_contains_session_id(mock_context):
    """Test that session ID is included in output."""
    toolbox = Toolbox(mock_context)

    result = toolbox._info(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    assert mock_context.session_id in result


def test_info_command_contains_model_info(mock_context):
    """Test that model information is included in output."""
    toolbox = Toolbox(mock_context)

    result = toolbox._info(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    assert "claude-3-5-sonnet-20241022" in result
    assert "8,192" in result  # max_tokens formatted with comma
    assert "200,000" in result  # context_window formatted with comma


def test_info_command_contains_thinking_mode(mock_context):
    """Test that thinking mode is displayed correctly."""
    toolbox = Toolbox(mock_context)

    result = toolbox._info(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    assert "💭 Normal (8k tokens)" in result

    # Test with thinking mode off
    mock_context.thinking_mode = "off"
    result = toolbox._info(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )
    assert "Off" in result


def test_info_command_contains_message_count(mock_context):
    """Test that message count is included."""
    toolbox = Toolbox(mock_context)

    result = toolbox._info(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    assert "Message Count:** 4" in result


def test_info_command_contains_token_usage(mock_context):
    """Test that token usage information is included."""
    toolbox = Toolbox(mock_context)

    result = toolbox._info(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    assert "Input Tokens:** 100" in result
    assert "Output Tokens:** 50" in result
    assert "cached: 20" in result
    assert "Total Tokens:** 150" in result


def test_info_command_contains_cost(mock_context):
    """Test that cost information is included."""
    toolbox = Toolbox(mock_context)

    result = toolbox._info(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    assert "Session Cost:**" in result
    # Cost should be formatted to 4 decimal places
    assert "$0.0010" in result or "$0.0011" in result


def test_info_command_with_conversation_size(mock_context):
    """Test that conversation size and compaction info are displayed when available."""
    toolbox = Toolbox(mock_context)

    result = toolbox._info(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    assert "Conversation Size:** 1,500 tokens" in result
    assert "% of context" in result
    assert "Tokens Until Compaction:**" in result


def test_info_command_with_thinking_tokens(mock_context):
    """Test that thinking tokens are displayed when present."""
    # Add thinking tokens to usage
    mock_context.usage_summary.return_value["total_thinking_tokens"] = 5000
    mock_context.usage_summary.return_value["thinking_cost"] = 0.045

    toolbox = Toolbox(mock_context)

    result = toolbox._info(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    assert "Thinking Tokens:** 5,000" in result
    assert "Thinking Cost:** $0.0450" in result


def test_info_command_with_parent_session(mock_context):
    """Test that parent session ID is shown when present."""
    mock_context.parent_session_id = "parent-session-id-12345"

    toolbox = Toolbox(mock_context)

    result = toolbox._info(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    assert "Parent Session ID:**" in result
    assert "parent-session-id-12345" in result


def test_info_command_with_session_metadata(mock_context, tmp_path):
    """Test that session metadata is read and displayed."""
    # Set history_base_dir on the mock context
    mock_context.history_base_dir = tmp_path / ".silica" / "personas" / "default"

    # Create a mock session file with metadata
    history_dir = (
        tmp_path
        / ".silica"
        / "personas"
        / "default"
        / "history"
        / mock_context.session_id
    )
    history_dir.mkdir(parents=True)

    session_file = history_dir / "root.json"
    session_data = {
        "session_id": mock_context.session_id,
        "metadata": {
            "created_at": "2024-01-01T12:00:00Z",
            "last_updated": "2024-01-01T13:30:00Z",
            "root_dir": "/home/user/project",
        },
        "messages": mock_context.chat_history,
    }

    with open(session_file, "w") as f:
        json.dump(session_data, f)

    # Mock Path.home() to return our temp directory
    original_home = Path.home

    def mock_home():
        return tmp_path

    Path.home = staticmethod(mock_home)

    try:
        toolbox = Toolbox(mock_context)

        result = toolbox._info(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )

        assert "Created:**" in result
        assert "Last Updated:**" in result
        assert "Working Directory:** `/home/user/project`" in result
    finally:
        # Restore original Path.home
        Path.home = staticmethod(original_home)


def test_info_command_registered_in_toolbox(mock_context):
    """Test that the info command is registered in the toolbox."""
    toolbox = Toolbox(mock_context)

    assert "info" in toolbox.local
    assert (
        toolbox.local["info"]["docstring"]
        == "Show statistics about the current session"
    )
