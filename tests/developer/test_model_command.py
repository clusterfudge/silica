import pytest
from unittest.mock import AsyncMock, Mock, patch

from silica.developer.context import AgentContext
from silica.developer.toolbox import Toolbox
from silica.developer.models import get_model
from silica.developer.sandbox import SandboxMode


@pytest.fixture
def mock_context(persona_base_dir):
    """Create a mock agent context for testing"""
    mock_ui = Mock()
    mock_ui.get_user_choice = AsyncMock()
    Mock()

    context = AgentContext.create(
        model_spec=get_model("sonnet"),
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=mock_ui,
        persona_base_directory=persona_base_dir,
    )

    return context


@pytest.mark.asyncio
async def test_model_command_no_args_shows_selector(mock_context):
    """Test that /model with no arguments shows interactive selector"""
    toolbox = Toolbox(mock_context)

    # User selects haiku from the interactive picker
    mock_context.user_interface.get_user_choice.return_value = (
        "haiku (claude-haiku-4-5-20251001)"
    )

    result = await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    # Should have called get_user_choice with model options
    mock_context.user_interface.get_user_choice.assert_called_once()
    call_args = mock_context.user_interface.get_user_choice.call_args[0]
    question = call_args[0]
    options = call_args[1]

    assert "Select a model" in question
    assert any("opus" in opt for opt in options)
    assert any("sonnet" in opt for opt in options)
    assert any("haiku" in opt for opt in options)

    # Should have switched to the selected model
    assert result is not None
    assert "Model changed to:" in result
    assert "claude-haiku-4-5-20251001" in result
    assert mock_context.model_spec["title"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_model_command_no_args_cancelled(mock_context):
    """Test that cancelling the selector returns None"""
    toolbox = Toolbox(mock_context)

    mock_context.user_interface.get_user_choice.return_value = "cancelled"

    result = await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    assert result is None
    # Model should remain unchanged
    assert mock_context.model_spec["title"] == "claude-sonnet-4-5-20250929"


@pytest.mark.asyncio
async def test_model_command_no_args_current_model_marked(mock_context):
    """Test that the current model is marked with ✓ in the selector"""
    toolbox = Toolbox(mock_context)

    mock_context.user_interface.get_user_choice.return_value = "cancelled"

    await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    options = mock_context.user_interface.get_user_choice.call_args[0][1]
    # The current model (sonnet) should have a ✓ marker
    sonnet_option = [opt for opt in options if "sonnet" in opt and "3.5" not in opt and "3.7" not in opt][0]
    assert "✓" in sonnet_option


@pytest.mark.asyncio
async def test_model_command_no_args_includes_api_models(mock_context):
    """Test that API models are included when available"""
    toolbox = Toolbox(mock_context)

    mock_context.user_interface.get_user_choice.return_value = "cancelled"

    # Mock the Anthropic API response
    mock_model = Mock()
    mock_model.id = "claude-3-5-haiku-20241022"
    mock_model.display_name = "Claude Haiku 3.5"

    mock_response = Mock()
    mock_response.data = [mock_model]

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.models.list.return_value = mock_response

        await toolbox._model(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )

    options = mock_context.user_interface.get_user_choice.call_args[0][1]
    # Should include the API model (not in MODEL_MAP short names)
    assert any("claude-3-5-haiku-20241022" in opt for opt in options)
    # Should have a separator
    assert any("api models" in opt for opt in options)


@pytest.mark.asyncio
async def test_model_command_no_args_api_failure_graceful(mock_context):
    """Test that API failure still shows short names"""
    toolbox = Toolbox(mock_context)

    mock_context.user_interface.get_user_choice.return_value = "cancelled"

    with patch("anthropic.Anthropic", side_effect=Exception("API unavailable")):
        await toolbox._model(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )

    # Should still show the selector with short names
    options = mock_context.user_interface.get_user_choice.call_args[0][1]
    assert any("opus" in opt for opt in options)
    assert any("sonnet" in opt for opt in options)
    assert any("haiku" in opt for opt in options)


@pytest.mark.asyncio
async def test_model_command_select_api_model(mock_context):
    """Test selecting a model from the API list"""
    toolbox = Toolbox(mock_context)

    mock_context.user_interface.get_user_choice.return_value = (
        "claude-sonnet-4-6 — Claude Sonnet 4.6"
    )

    result = await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="",
    )

    assert result is not None
    assert "Model changed to:" in result
    assert "claude-sonnet-4-6" in result


@pytest.mark.asyncio
async def test_model_command_change_model_by_short_name(mock_context):
    """Test changing model using short name"""
    toolbox = Toolbox(mock_context)

    # Change to haiku
    result = await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="haiku",
    )

    assert "Model changed to:" in result
    assert "claude-haiku-4-5-20251001" in result
    assert "haiku" in result

    # Verify the context was updated
    assert mock_context.model_spec["title"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_model_command_change_model_by_full_name(mock_context):
    """Test changing model using full model name"""
    toolbox = Toolbox(mock_context)

    # Change to opus using full name
    result = await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="claude-opus-4-6",
    )

    assert "Model changed to:" in result
    assert "claude-opus-4-6" in result
    assert "opus" in result

    # Verify the context was updated
    assert mock_context.model_spec["title"] == "claude-opus-4-6"


@pytest.mark.asyncio
async def test_model_command_invalid_model_name(mock_context):
    """Test that unregistered model names use Opus fallback"""
    toolbox = Toolbox(mock_context)

    # Use a custom/unregistered model name
    result = await toolbox._model(
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


@pytest.mark.asyncio
async def test_model_command_case_insensitive(mock_context):
    """Test that model names are handled case-insensitively"""
    toolbox = Toolbox(mock_context)

    # Try uppercase
    result = await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="HAIKU",
    )

    # Should still work
    assert "Model changed to:" in result
    assert mock_context.model_spec["title"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_model_command_whitespace_handling(mock_context):
    """Test that extra whitespace is handled properly"""
    toolbox = Toolbox(mock_context)

    result = await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="  haiku  ",
    )

    assert "Model changed to:" in result
    assert mock_context.model_spec["title"] == "claude-haiku-4-5-20251001"
