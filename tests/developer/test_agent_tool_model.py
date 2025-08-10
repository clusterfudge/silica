import pytest
from unittest.mock import patch, MagicMock

from silica.developer.context import AgentContext
from silica.developer.models import get_model
from silica.developer.tools.subagent import agent
from silica.developer.user_interface import UserInterface
from silica.developer.sandbox import Sandbox
from silica.developer.memory import MemoryManager


@pytest.fixture
def mock_agent_run():
    with patch("silica.developer.agent_loop.run") as mock_run:
        yield mock_run


@pytest.fixture
def agent_context():
    # Setup test model spec
    model_spec = {
        "title": "claude-3-sonnet-20240229",
        "pricing": {"input": 3.0, "output": 15.0},
        "cache_pricing": {"write": 3.0, "read": 0.6},
        "max_tokens": 4096,
    }

    # Create mocks
    mock_ui = MagicMock(spec=UserInterface)
    mock_sandbox = MagicMock(spec=Sandbox)
    mock_memory_manager = MagicMock(spec=MemoryManager)

    # Create context
    context = AgentContext(
        parent_session_id=None,
        session_id="test-session",
        model_spec=model_spec,
        sandbox=mock_sandbox,
        user_interface=mock_ui,
        usage=[],
        memory_manager=mock_memory_manager,
    )

    return context


async def test_agent_tool_with_default_model(agent_context, mock_agent_run):
    # Setup
    mock_agent_run.return_value = [
        {"role": "user", "content": "test prompt"},
        {"role": "assistant", "content": "test response"},
    ]

    # Execute
    result = await agent(agent_context, "test prompt", "web_search")

    # Verify
    assert mock_agent_run.call_count == 1
    assert mock_agent_run.call_args.kwargs["tool_names"] == ["web_search"]
    # Should use the default model from the context
    assert "claude-3-sonnet-20240229" == agent_context.model_spec["title"]
    # The result should be the assistant's response
    assert result == "test response"


async def test_agent_tool_with_custom_model(agent_context, mock_agent_run):
    # Setup
    mock_agent_run.return_value = [
        {"role": "user", "content": "test prompt"},
        {"role": "assistant", "content": "test response with custom model"},
    ]

    # Execute with custom model parameter using the 'light' alias
    result = await agent(agent_context, "test prompt", "web_search", model="light")

    # Verify that run was called with a context having the specified model
    assert mock_agent_run.call_count == 1

    # Extract the AgentContext object passed to run()
    context_arg = mock_agent_run.call_args.kwargs["agent_context"]

    # Verify the model was changed in the sub-agent context to the haiku model
    assert context_arg.model_spec["title"] == get_model("haiku")["title"]

    # The original context should remain unchanged
    assert agent_context.model_spec["title"] == "claude-3-sonnet-20240229"

    # The result should be the assistant's response
    assert result == "test response with custom model"


async def test_agent_tool_with_smart_model(agent_context, mock_agent_run):
    # Setup
    mock_agent_run.return_value = [
        {"role": "user", "content": "test prompt"},
        {"role": "assistant", "content": "test response with smart model"},
    ]

    # Execute with the 'smart' alias
    result = await agent(agent_context, "test prompt", "web_search", model="smart")

    # Verify
    assert mock_agent_run.call_count == 1

    # Extract the AgentContext object passed to run()
    context_arg = mock_agent_run.call_args.kwargs["agent_context"]

    # Verify the model was set to the 'smart' alias's corresponding model
    assert context_arg.model_spec["title"] == get_model("sonnet")["title"]

    # The result should be the assistant's response
    assert result == "test response with smart model"


async def test_agent_tool_with_invalid_model(agent_context, mock_agent_run):
    # Setup
    mock_agent_run.return_value = [
        {"role": "user", "content": "test prompt"},
        {"role": "assistant", "content": "test response"},
    ]

    # Execute with an invalid model alias - should fall back to the default
    result = await agent(
        agent_context, "test prompt", "web_search", model="nonexistent"
    )

    # Verify
    assert mock_agent_run.call_count == 1

    # Extract the AgentContext object passed to run()
    context_arg = mock_agent_run.call_args.kwargs["agent_context"]

    # Since the model alias is invalid, it should use the default model from the original context
    assert context_arg.model_spec["title"] == "claude-3-sonnet-20240229"

    # The result should be the assistant's response
    assert result == "test response"
