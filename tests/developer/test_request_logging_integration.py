"""Integration tests for request/response logging with agent loop."""

import json
import tempfile
from pathlib import Path
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from silica.developer.agent_loop import run
from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode


@pytest.fixture
def temp_log_file():
    """Create a temporary log file."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
        log_path = Path(f.name)
    yield log_path
    # Cleanup
    if log_path.exists():
        log_path.unlink()


@pytest.fixture
def mock_user_interface():
    """Create a mock user interface."""
    ui = Mock()
    ui.handle_system_message = Mock()
    ui.handle_assistant_message = Mock()
    ui.handle_user_input = Mock()
    ui.handle_tool_result = Mock()
    ui.display_token_count = Mock()
    ui.display_welcome_message = Mock()
    ui.status = Mock()
    ui.status.return_value.__enter__ = Mock()
    ui.status.return_value.__exit__ = Mock()
    ui.get_user_input = AsyncMock(return_value="/quit")
    ui.set_toolbox = Mock()
    return ui


@pytest.fixture
def agent_context(mock_user_interface):
    """Create an agent context for testing."""
    return AgentContext.create(
        model_spec={
            "title": "claude-3-5-sonnet-20241022",
            "max_tokens": 4096,
            "thinking_support": False,
        },
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=mock_user_interface,
    )


@pytest.mark.asyncio
async def test_logging_integration(agent_context, temp_log_file, monkeypatch):
    """Test that logging integrates properly with the agent loop."""
    # Mock the Anthropic API client
    mock_client = MagicMock()
    mock_stream = MagicMock()

    # Create a mock response message
    mock_message = MagicMock()
    mock_message.id = "msg_test_123"
    mock_message.content = [MagicMock(type="text", text="Test response")]
    mock_message.usage = MagicMock(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    mock_message.stop_reason = "end_turn"

    mock_stream.get_final_message.return_value = mock_message
    mock_stream.response.headers = {}
    mock_stream.__enter__ = Mock(return_value=mock_stream)
    mock_stream.__exit__ = Mock()
    mock_stream.__iter__ = Mock(return_value=iter([]))

    mock_client.messages.stream.return_value = mock_stream

    # Patch the client creation
    with patch(
        "silica.developer.agent_loop.anthropic.Client", return_value=mock_client
    ):
        # Set the API key
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        # Run the agent loop with logging enabled
        await run(
            agent_context=agent_context,
            initial_prompt="Hello",
            single_response=True,
            log_file_path=str(temp_log_file),
        )

    # Verify that the log file was created and contains entries
    assert temp_log_file.exists()

    with open(temp_log_file) as f:
        log_lines = f.readlines()

    # Should have at least a request and a response
    assert len(log_lines) >= 2

    # Parse and verify the request entry
    request_entry = json.loads(log_lines[0])
    assert request_entry["type"] == "request"
    assert request_entry["model"] == "claude-3-5-sonnet-20241022"
    assert "messages" in request_entry
    assert len(request_entry["messages"]) > 0
    assert request_entry["messages"][0]["content"] == "Hello"

    # Parse and verify the response entry
    response_entry = json.loads(log_lines[1])
    assert response_entry["type"] == "response"
    assert response_entry["message_id"] == "msg_test_123"
    assert response_entry["stop_reason"] == "end_turn"
    assert response_entry["usage"]["input_tokens"] == 100
    assert response_entry["usage"]["output_tokens"] == 50


@pytest.mark.asyncio
async def test_logging_disabled_by_default(agent_context, monkeypatch):
    """Test that logging is disabled when no log file is specified."""
    # Mock the Anthropic API client
    mock_client = MagicMock()
    mock_stream = MagicMock()

    mock_message = MagicMock()
    mock_message.id = "msg_test_123"
    mock_message.content = [MagicMock(type="text", text="Test response")]
    mock_message.usage = MagicMock(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    mock_message.stop_reason = "end_turn"

    mock_stream.get_final_message.return_value = mock_message
    mock_stream.response.headers = {}
    mock_stream.__enter__ = Mock(return_value=mock_stream)
    mock_stream.__exit__ = Mock()
    mock_stream.__iter__ = Mock(return_value=iter([]))

    mock_client.messages.stream.return_value = mock_stream

    with patch(
        "silica.developer.agent_loop.anthropic.Client", return_value=mock_client
    ):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        # Run without specifying log_file_path (default is None)
        await run(
            agent_context=agent_context,
            initial_prompt="Hello",
            single_response=True,
            # log_file_path not specified - should default to None
        )

    # Test passes if no exceptions are raised
    assert True
