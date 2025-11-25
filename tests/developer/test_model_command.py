import pytest
from unittest.mock import Mock

from silica.developer.context import AgentContext
from silica.developer.toolbox import Toolbox
from silica.developer.models import get_model
from silica.developer.sandbox import SandboxMode


@pytest.fixture
def mock_context(persona_base_dir):
    """Create a mock agent context for testing"""
    mock_ui = Mock()
    Mock()

    context = AgentContext.create(
        model_spec=get_model("sonnet"),
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=mock_ui,
        persona_base_directory=persona_base_dir,
    )

    return context


def test_model_command_no_args_shows_current(mock_context):
    """Test that /model with no arguments shows current model info"""
    toolbox = Toolbox(mock_context)

    result = toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    # The method now calls user_interface.handle_system_message() and returns None
    assert result is None

    # Check that the user interface received the correct message
    mock_context.user_interface.handle_system_message.assert_called_once()
    call_args = mock_context.user_interface.handle_system_message.call_args[0][0]

    assert "Current Model:" in call_args
    assert "claude-sonnet-4-5-20250929" in call_args
    assert "sonnet" in call_args
    assert "Max Tokens:" in call_args
    assert "Context Window:" in call_args
    assert "Pricing:" in call_args


def test_model_command_change_model_by_short_name(mock_context):
    """Test changing model using short name"""
    toolbox = Toolbox(mock_context)

    # Change to haiku
    result = toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="haiku",
    )

    assert "Model changed to:" in result
    assert "claude-3-5-haiku-20241022" in result
    assert "haiku" in result

    # Verify the context was updated
    assert mock_context.model_spec["title"] == "claude-3-5-haiku-20241022"


def test_model_command_change_model_by_full_name(mock_context):
    """Test changing model using full model name"""
    toolbox = Toolbox(mock_context)

    # Change to opus using full name
    result = toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="claude-opus-4-5-20251101",
    )

    assert "Model changed to:" in result
    assert "claude-opus-4-5-20251101" in result
    assert "opus" in result

    # Verify the context was updated
    assert mock_context.model_spec["title"] == "claude-opus-4-5-20251101"


def test_model_command_invalid_model_name(mock_context):
    """Test that unregistered model names use Opus fallback"""
    toolbox = Toolbox(mock_context)

    # Use a custom/unregistered model name
    result = toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="invalid-model",
    )

    # Should succeed and show the custom model name
    assert "Model changed to:" in result
    assert "invalid-model" in result

    # Verify the context was updated with custom model
    assert mock_context.model_spec["title"] == "invalid-model"

    # Verify it uses Opus pricing/limits as fallback
    opus = get_model("opus")
    assert mock_context.model_spec["pricing"] == opus["pricing"]
    assert mock_context.model_spec["max_tokens"] == opus["max_tokens"]


def test_model_command_case_insensitive(mock_context):
    """Test that model names are handled case-insensitively"""
    toolbox = Toolbox(mock_context)

    # Try uppercase
    result = toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="HAIKU",
    )

    # Should still work
    assert "Model changed to:" in result
    assert mock_context.model_spec["title"] == "claude-3-5-haiku-20241022"


def test_model_command_whitespace_handling(mock_context):
    """Test that extra whitespace is handled properly"""
    toolbox = Toolbox(mock_context)

    result = toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="  haiku  ",
    )

    assert "Model changed to:" in result
    assert mock_context.model_spec["title"] == "claude-3-5-haiku-20241022"
