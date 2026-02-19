import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from anthropic.types import Usage

from silica.developer.context import AgentContext
from silica.developer.session_store import SessionStore
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


@pytest.fixture
def mock_usage():
    """Mock usage data."""
    return Usage(
        input_tokens=100,
        output_tokens=25,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


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


def test_flush_root_context(
    home_dir_patch,
    temp_dir,
    mock_sandbox,
    mock_user_interface,
    mock_memory_manager,
    model_spec,
    mock_usage,
):
    """Test flushing a root context creates v2 split files."""
    context = create_test_context(
        mock_sandbox, mock_user_interface, mock_memory_manager, model_spec
    )
    context.report_usage(mock_usage, model_spec)

    chat_history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]

    context.flush(chat_history)

    history_dir = (
        Path(temp_dir.name)
        / ".silica"
        / "personas"
        / "default"
        / "history"
        / context.session_id
    )

    # v2 files should exist
    assert (history_dir / "session.json").exists()
    assert (history_dir / "root.history.jsonl").exists()
    assert (history_dir / "root.context.jsonl").exists()

    # Read via SessionStore
    store = SessionStore(history_dir)
    ctx_msgs = store.read_context()
    assert len(ctx_msgs) == 2
    assert ctx_msgs[0]["content"] == "Hello"
    assert ctx_msgs[1]["content"] == "Hi there"

    meta = store.read_session_meta()
    assert meta["session_id"] == context.session_id


def test_flush_sub_agent_context(
    home_dir_patch,
    temp_dir,
    mock_sandbox,
    mock_user_interface,
    mock_memory_manager,
    model_spec,
    mock_usage,
):
    """Test flushing a sub-agent context creates its own v2 files."""
    root_context = create_test_context(
        mock_sandbox, mock_user_interface, mock_memory_manager, model_spec
    )

    sub_context = create_test_context(
        mock_sandbox,
        mock_user_interface,
        mock_memory_manager,
        model_spec,
        parent_id=root_context.session_id,
    )
    sub_context.report_usage(mock_usage, model_spec)

    chat_history = [
        {"role": "user", "content": "Execute this subtask"},
        {"role": "assistant", "content": "Subtask completed"},
    ]

    sub_context.flush(chat_history)

    history_dir = (
        Path(temp_dir.name)
        / ".silica"
        / "personas"
        / "default"
        / "history"
        / root_context.session_id
    )

    # Sub-agent v2 files
    assert (history_dir / f"{sub_context.session_id}.history.jsonl").exists()
    assert (history_dir / f"{sub_context.session_id}.context.jsonl").exists()

    store = SessionStore(history_dir, agent_name=sub_context.session_id)
    ctx_msgs = store.read_context()
    assert len(ctx_msgs) == 2
    assert ctx_msgs[0]["content"] == "Execute this subtask"


async def test_agent_tool_creates_correct_context(
    home_dir_patch, mock_sandbox, mock_user_interface, mock_memory_manager, model_spec
):
    """Test that the agent tool creates a context with the correct parent_session_id"""
    with patch("silica.developer.agent_loop.run") as mock_run:
        from silica.developer.tools.subagent import agent

        parent_context = create_test_context(
            mock_sandbox, mock_user_interface, mock_memory_manager, model_spec
        )

        async def mock_run_async(*args, **kwargs):
            return []

        mock_run.side_effect = mock_run_async

        with patch("silica.developer.tools.subagent.CaptureInterface") as mock_capture:
            mock_capture_instance = MagicMock()
            mock_capture.return_value = mock_capture_instance

            await agent(parent_context, "Do something", "read_file")

            args, kwargs = mock_run.call_args
            agent_context = kwargs.get("agent_context")

            assert agent_context is not None
            assert agent_context.parent_session_id == parent_context.session_id
            assert agent_context.session_id != parent_context.session_id


def test_sub_agent_flush_directory_structure(
    home_dir_patch,
    temp_dir,
    mock_sandbox,
    mock_user_interface,
    mock_memory_manager,
    model_spec,
):
    """Test that sub-agent contexts flush to the correct directory structure"""
    root_context = create_test_context(
        mock_sandbox, mock_user_interface, mock_memory_manager, model_spec
    )

    sub_context = AgentContext(
        session_id=str(uuid4()),
        parent_session_id=root_context.session_id,
        model_spec=model_spec,
        sandbox=mock_sandbox,
        user_interface=mock_user_interface,
        usage=[],
        memory_manager=mock_memory_manager,
    )

    chat_history = [
        {"role": "user", "content": "Execute subtask"},
        {"role": "assistant", "content": "Done"},
    ]

    root_context.flush(chat_history)
    sub_context.flush(chat_history)

    # Root's v2 files
    root_dir = (
        Path(temp_dir.name)
        / ".silica"
        / "personas"
        / "default"
        / "history"
        / root_context.session_id
    )
    assert (root_dir / "session.json").exists()
    assert (root_dir / "root.history.jsonl").exists()

    # Sub-agent's v2 files in parent's directory
    assert (root_dir / f"{sub_context.session_id}.history.jsonl").exists()
    assert (root_dir / f"{sub_context.session_id}.context.jsonl").exists()

    # Verify sub-agent content
    sub_store = SessionStore(root_dir, agent_name=sub_context.session_id)
    ctx_msgs = sub_store.read_context()
    assert len(ctx_msgs) == 2
    assert ctx_msgs[0]["content"] == "Execute subtask"
