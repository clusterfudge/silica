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
    # Simulate HybridUserInterface.cli — the model selector uses cli directly
    # to avoid pushing dialogs over the AgentIsland bridge
    mock_ui.cli = Mock()
    mock_ui.cli.get_user_choice = mock_ui.get_user_choice
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

    # Returns None — output rendered internally via handle_system_message
    assert result is None

    # Should have switched to the selected model
    mock_context.user_interface.handle_system_message.assert_called()
    msg = mock_context.user_interface.handle_system_message.call_args[0][0]
    assert "Model changed to:" in msg
    assert "claude-haiku-4-5-20251001" in msg
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
    sonnet_option = [opt for opt in options if "sonnet" in opt and "4-5" in opt][0]
    assert "✓" in sonnet_option


def _make_api_response(models):
    """Helper to create a mock paginated API response."""
    mock_response = Mock()
    mock_response.data = models
    mock_response.has_more = False
    return mock_response


def _make_api_model(model_id, display_name, max_tokens=64000, max_input_tokens=200000):
    """Helper to create a mock API model."""
    m = Mock()
    m.id = model_id
    m.display_name = display_name
    m.model_dump = Mock(
        return_value={
            "max_tokens": max_tokens,
            "max_input_tokens": max_input_tokens,
        }
    )
    return m


@pytest.mark.asyncio
async def test_model_command_no_args_includes_api_models(mock_context):
    """Test that API models are included when available"""
    toolbox = Toolbox(mock_context)

    mock_context.user_interface.get_user_choice.return_value = "cancelled"

    mock_model = _make_api_model(
        "claude-sonnet-4-6", "Claude Sonnet 4.6", 128000, 1000000
    )
    mock_response = _make_api_response([mock_model])

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.models.list.return_value = mock_response

        await toolbox._model(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )

    options = mock_context.user_interface.get_user_choice.call_args[0][1]
    # Should include the API model (not in MODEL_MAP short names)
    assert any("claude-sonnet-4-6" in opt for opt in options)
    # Should NOT have separator lines as selectable options
    assert not any(opt.startswith("─") for opt in options)


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
async def test_model_command_no_args_includes_non_claude_models(mock_context):
    """Test that non-claude models (fennec etc.) are included"""
    toolbox = Toolbox(mock_context)

    mock_context.user_interface.get_user_choice.return_value = "cancelled"

    mock_fennec = _make_api_model(
        "fennec-v7-ext-fast", "fennec-v7-ext-fast", 128000, 200000
    )
    mock_response = _make_api_response([mock_fennec])

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.models.list.return_value = mock_response

        await toolbox._model(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )

    options = mock_context.user_interface.get_user_choice.call_args[0][1]
    assert any("fennec-v7-ext-fast" in opt for opt in options)


@pytest.mark.asyncio
async def test_model_command_no_args_excludes_claude_3(mock_context):
    """Test that Claude 3 family models are excluded from the selector"""
    toolbox = Toolbox(mock_context)

    mock_context.user_interface.get_user_choice.return_value = "cancelled"

    mock_claude3 = _make_api_model("claude-3-haiku-20240307", "Claude Haiku 3")
    mock_claude35 = _make_api_model("claude-3-5-haiku-20241022", "Claude Haiku 3.5")
    mock_claude4 = _make_api_model(
        "claude-sonnet-4-6", "Claude Sonnet 4.6", 128000, 1000000
    )
    mock_response = _make_api_response([mock_claude3, mock_claude35, mock_claude4])

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.models.list.return_value = mock_response

        await toolbox._model(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )

    options = mock_context.user_interface.get_user_choice.call_args[0][1]
    # Claude 3 family should be excluded
    assert not any("claude-3-haiku" in opt for opt in options)
    assert not any("claude-3-5-haiku" in opt for opt in options)
    # Claude 3 short name aliases should also be excluded
    assert not any("sonnet-3.5" in opt for opt in options)
    assert not any("sonnet-3.7" in opt for opt in options)
    # Claude 4+ should be included
    assert any("claude-sonnet-4-6" in opt for opt in options)


@pytest.mark.asyncio
async def test_model_command_no_args_excludes_entropy_suffixes(mock_context):
    """Test that models with high-entropy suffixes (fine-tune snapshots) are excluded"""
    toolbox = Toolbox(mock_context)

    mock_context.user_interface.get_user_choice.return_value = "cancelled"

    mock_normal = _make_api_model(
        "fennec-v7-ext-fast", "fennec-v7-ext-fast", 128000, 200000
    )
    mock_ft_snap = _make_api_model(
        "claude-haiku-4-5-20251001-ft_snap_01QS7VSpz8mq2S5g66MdQYGz",
        "Fine-tuned Haiku",
    )
    mock_response = _make_api_response([mock_normal, mock_ft_snap])

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.models.list.return_value = mock_response

        await toolbox._model(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )

    options = mock_context.user_interface.get_user_choice.call_args[0][1]
    assert any("fennec-v7-ext-fast" in opt for opt in options)
    assert not any("ft_snap" in opt for opt in options)


@pytest.mark.asyncio
async def test_model_command_no_args_caches_api_call(mock_context):
    """Test that the API call is cached across invocations"""
    toolbox = Toolbox(mock_context)

    mock_context.user_interface.get_user_choice.return_value = "cancelled"

    mock_model = _make_api_model(
        "claude-sonnet-4-6", "Claude Sonnet 4.6", 128000, 1000000
    )
    mock_response = _make_api_response([mock_model])

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.models.list.return_value = mock_response

        # Call twice
        await toolbox._model(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )
        await toolbox._model(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )

        # API should only be called once (cached)
        assert mock_anthropic.return_value.models.list.call_count == 1


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

    assert result is None
    msg = mock_context.user_interface.handle_system_message.call_args[0][0]
    assert "Model changed to:" in msg
    assert "claude-sonnet-4-6" in msg


@pytest.mark.asyncio
async def test_model_command_select_uses_api_token_limits(mock_context):
    """Test that selecting a model from API uses its token limits"""
    toolbox = Toolbox(mock_context)

    mock_context.user_interface.get_user_choice.return_value = (
        "fennec-v7-ext-fast — fennec-v7-ext-fast"
    )

    mock_fennec = _make_api_model(
        "fennec-v7-ext-fast",
        "fennec-v7-ext-fast",
        max_tokens=128000,
        max_input_tokens=200000,
    )
    mock_response = _make_api_response([mock_fennec])

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.models.list.return_value = mock_response

        await toolbox._model(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )

    # Should use API-provided limits, not hardcoded Opus fallback
    assert mock_context.model_spec["title"] == "fennec-v7-ext-fast"
    assert mock_context.model_spec["max_output_tokens"] == 128000
    assert mock_context.model_spec["context_window"] == 200000


@pytest.mark.asyncio
async def test_model_command_direct_uses_api_token_limits(mock_context):
    """Test that /model <name> fetches token limits from API"""
    toolbox = Toolbox(mock_context)

    mock_model = Mock()
    mock_model.id = "fennec-v7-ext-fast"
    mock_model.display_name = "fennec-v7-ext-fast"
    mock_model.model_dump = Mock(
        return_value={
            "max_tokens": 128000,
            "max_input_tokens": 200000,
        }
    )

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.models.retrieve.return_value = mock_model

        await toolbox._model(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="fennec-v7-ext-fast",
        )

    assert mock_context.model_spec["title"] == "fennec-v7-ext-fast"
    assert mock_context.model_spec["max_output_tokens"] == 128000
    assert mock_context.model_spec["context_window"] == 200000


@pytest.mark.asyncio
async def test_model_command_change_model_by_short_name(mock_context):
    """Test changing model using short name"""
    toolbox = Toolbox(mock_context)

    result = await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="haiku",
    )

    assert result is None
    msg = mock_context.user_interface.handle_system_message.call_args[0][0]
    assert "Model changed to:" in msg
    assert "claude-haiku-4-5-20251001" in msg
    assert "haiku" in msg
    assert mock_context.model_spec["title"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_model_command_change_model_by_full_name(mock_context):
    """Test changing model using full model name"""
    toolbox = Toolbox(mock_context)

    result = await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="claude-opus-4-6",
    )

    assert result is None
    msg = mock_context.user_interface.handle_system_message.call_args[0][0]
    assert "Model changed to:" in msg
    assert "claude-opus-4-6" in msg
    assert "opus" in msg
    assert mock_context.model_spec["title"] == "claude-opus-4-6"


@pytest.mark.asyncio
async def test_model_command_invalid_model_name(mock_context):
    """Test that unregistered model names use Opus fallback"""
    toolbox = Toolbox(mock_context)

    result = await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="invalid-model",
    )

    assert result is None
    msg = mock_context.user_interface.handle_system_message.call_args[0][0]
    assert "Model changed to:" in msg
    assert "invalid-model" in msg

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

    result = await toolbox._model(
        user_interface=mock_context.user_interface,
        sandbox=mock_context.sandbox,
        user_input="HAIKU",
    )

    assert result is None
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

    assert result is None
    assert mock_context.model_spec["title"] == "claude-haiku-4-5-20251001"
