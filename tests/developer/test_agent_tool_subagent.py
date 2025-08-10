import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from silica.developer.context import AgentContext
from silica.developer.tools.subagent import agent
from silica.developer.memory import MemoryManager


class JsonSerializableMock:
    """A mock object that can be JSON serialized"""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    temp_dir = TemporaryDirectory()
    yield temp_dir
    temp_dir.cleanup()


@pytest.fixture
def home_dir_patch(temp_dir):
    """Patch the home directory to use our temp directory."""
    with patch("pathlib.Path.home") as mock_home:
        mock_home.return_value = Path(temp_dir.name)
        yield mock_home


@pytest.fixture
def mock_memory_manager():
    """Create a mock memory manager."""
    return MagicMock(spec=MemoryManager)


@pytest.fixture
def mock_sandbox():
    """Create a mock sandbox."""
    return JsonSerializableMock(
        check_permissions=lambda *args: True,
        read_file=lambda path: f"Content of {path}",
        write_file=lambda path, content: None,
        get_directory_listing=lambda path, recursive: [path],
    )


@pytest.fixture
def mock_user_interface():
    """Create a mock user interface."""

    # Add a status method that returns a context manager
    class DummyStatus:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def update(self, *args, **kwargs):
            pass

    mock_ui = JsonSerializableMock(
        get_user_input=lambda prompt: "",
        display_welcome_message=lambda: None,
        handle_system_message=lambda msg: None,
        handle_user_input=lambda msg: None,
        handle_assistant_message=lambda msg: None,
        handle_tool_use=lambda name, input: None,
        handle_tool_result=lambda name, result: None,
        display_token_count=lambda *args: None,
        permission_callback=lambda *args: True,
        permission_rendering_callback=lambda *args: True,
        bare=lambda *args: None,
    )

    mock_ui.status = lambda *args, **kwargs: DummyStatus()
    return mock_ui


@pytest.fixture
def model_spec():
    """Create a model specification for testing."""
    return {
        "title": "test-model",
        "pricing": {"input": 3.00, "output": 15.00},
        "cache_pricing": {"write": 3.75, "read": 0.30},
    }


def create_test_context(
    mock_sandbox, mock_user_interface, mock_memory_manager, model_spec, parent_id=None
):
    """Helper to create a test context with proper serialization"""
    return AgentContext(
        session_id=str(uuid4()),
        parent_session_id=parent_id,
        model_spec=model_spec,
        sandbox=mock_sandbox,
        user_interface=mock_user_interface,
        usage=[],
        memory_manager=mock_memory_manager,
    )


async def test_agent_tool_nested_context_save(
    home_dir_patch,
    temp_dir,
    mock_sandbox,
    mock_user_interface,
    mock_memory_manager,
    model_spec,
):
    """Test that the agent tool properly saves nested context"""
    # Create a simple chat history
    chat_history = [
        {"role": "user", "content": "Do something"},
        {"role": "assistant", "content": "Task completed"},
    ]

    # Create a parent context
    parent_context = create_test_context(
        mock_sandbox, mock_user_interface, mock_memory_manager, model_spec
    )

    # Create a capture interface mock
    capture_interface_mock = MagicMock()
    captured_agent_context = None

    # Patch CaptureInterface constructor
    with patch(
        "silica.developer.tools.subagent.CaptureInterface"
    ) as mock_capture_class:
        mock_capture_class.return_value = capture_interface_mock

        # Mock agent.run to capture the agent_context and return chat history
        with patch("silica.developer.agent_loop.run") as mock_run:
            # Setup mock to save the passed context and return chat history
            async def capture_and_return(agent_context, **kwargs):
                nonlocal captured_agent_context
                # Save the agent_context for later inspection
                captured_agent_context = agent_context
                # IMPORTANT: Manually flush the chat history since our mock doesn't run the real agent.run
                # which would normally handle flushing in its finally block
                agent_context.flush(chat_history)
                # Return the chat history
                return chat_history

            mock_run.side_effect = capture_and_return

            # Call the agent tool
            await agent(parent_context, "Do a sub task", "read_file")

            # Verify a sub-agent context was created with parent's session ID
            assert (
                captured_agent_context is not None
            ), "agent.run was not called with an agent_context"
            assert captured_agent_context.parent_session_id == parent_context.session_id

            # Verify the chat history was flushed correctly
            history_dir = (
                Path(temp_dir.name) / ".hdev" / "history" / parent_context.session_id
            )
            sub_agent_file = history_dir / f"{captured_agent_context.session_id}.json"

            assert (
                sub_agent_file.exists()
            ), f"Sub-agent history file not found at {sub_agent_file}"

            # Read the content of the file to verify
            with open(sub_agent_file, "r") as f:
                saved_data = json.load(f)

            assert saved_data["session_id"] == captured_agent_context.session_id
            assert saved_data["parent_session_id"] == parent_context.session_id
            assert saved_data["messages"] == chat_history
