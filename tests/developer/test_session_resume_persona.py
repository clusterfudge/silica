"""
Test that session resumption correctly uses the persona directory.

This test ensures that when resuming a session, the correct persona directory
is used to load the session data, fixing the bug where sessions were always
looked up in the 'default' persona directory.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock

from silica.developer.context import AgentContext, load_session_data
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.user_interface import UserInterface


def test_load_session_data_uses_persona_directory():
    """Test that load_session_data uses the provided history_base_dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create engineer persona directory with session
        engineer_persona_dir = (
            Path(tmpdir) / ".silica" / "personas" / "autonomous_engineer"
        )
        session_id = "17774d67-180a-4d7f-8f2a-ff0d217ca602"
        engineer_session_dir = engineer_persona_dir / "history" / session_id
        engineer_session_dir.mkdir(parents=True)

        # Create a root.json in the engineer persona directory
        root_file = engineer_session_dir / "root.json"
        session_data = {
            "session_id": session_id,
            "parent_session_id": None,
            "model_spec": {"title": "test-model"},
            "usage": [],
            "messages": [
                {"role": "user", "content": "Hello from engineer persona"},
                {"role": "assistant", "content": "Hello!"},
            ],
            "thinking_mode": "off",
            "metadata": {
                "created_at": "2025-01-01T00:00:00Z",
                "last_updated": "2025-01-01T00:00:00Z",
                "root_dir": tmpdir,
                "cli_args": ["hdev"],
            },
        }

        with open(root_file, "w") as f:
            json.dump(session_data, f)

        # Create a mock user interface
        mock_ui = Mock(spec=UserInterface)
        mock_ui.permission_callback = Mock(return_value=True)
        mock_ui.permission_rendering_callback = Mock()

        # Create a sandbox
        sandbox = Sandbox(tmpdir, mode=SandboxMode.ALLOW_ALL)

        # Create a base context with the engineer persona directory
        base_context = AgentContext(
            session_id="new-session",
            parent_session_id=None,
            model_spec={"title": "test-model"},
            sandbox=sandbox,
            user_interface=mock_ui,
            usage=[],
            memory_manager=Mock(),
            history_base_dir=engineer_persona_dir,
        )

        # Load the session with explicit history_base_dir
        loaded_context = load_session_data(
            session_id, base_context, history_base_dir=engineer_persona_dir
        )

        # Verify the session was loaded successfully from engineer persona
        assert (
            loaded_context is not None
        ), "Session should be loaded from engineer persona"
        assert (
            loaded_context.chat_history[0]["content"] == "Hello from engineer persona"
        )

        # Verify the context has the correct history_base_dir
        assert loaded_context.history_base_dir == engineer_persona_dir


def test_agent_context_create_passes_persona_to_load_session():
    """
    Test that AgentContext.create passes persona_base_directory to load_session_data.

    This is the main bug fix test - ensuring that when a session is resumed,
    the persona directory is correctly propagated through AgentContext.create
    to load_session_data.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create engineer persona directory with session
        engineer_persona_dir = (
            Path(tmpdir) / ".silica" / "personas" / "autonomous_engineer"
        )
        session_id = "test-session-123"
        engineer_session_dir = engineer_persona_dir / "history" / session_id
        engineer_session_dir.mkdir(parents=True)

        # Create root.json
        root_file = engineer_session_dir / "root.json"
        session_data = {
            "session_id": session_id,
            "parent_session_id": None,
            "model_spec": {"title": "test-model"},
            "usage": [],
            "messages": [
                {"role": "user", "content": "Test message from engineer"},
            ],
            "thinking_mode": "off",
            "metadata": {
                "created_at": "2025-01-01T00:00:00Z",
                "last_updated": "2025-01-01T00:00:00Z",
                "root_dir": tmpdir,
                "cli_args": ["hdev"],
            },
        }

        with open(root_file, "w") as f:
            json.dump(session_data, f)

        # Create a mock user interface
        mock_ui = Mock(spec=UserInterface)
        mock_ui.permission_callback = Mock(return_value=True)
        mock_ui.permission_rendering_callback = Mock()
        mock_ui.handle_system_message = Mock()

        # Use AgentContext.create to load the session
        context = AgentContext.create(
            model_spec={"title": "test-model"},
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[tmpdir],
            user_interface=mock_ui,
            session_id=session_id,
            persona_base_directory=engineer_persona_dir,
        )

        # Verify the session was loaded
        assert context is not None
        assert len(context.chat_history) > 0
        assert context.chat_history[0]["content"] == "Test message from engineer"
        assert context.history_base_dir == engineer_persona_dir


def test_session_not_found_in_wrong_persona_directory():
    """
    Test that a session in one persona directory is not found when looking in another.

    This verifies that the bug was actually a problem - a session in the engineer
    persona directory should not be found when looking in the default directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create engineer persona directory with session
        engineer_persona_dir = (
            Path(tmpdir) / ".silica" / "personas" / "autonomous_engineer"
        )
        default_persona_dir = Path(tmpdir) / ".silica" / "personas" / "default"

        session_id = "test-session-456"
        engineer_session_dir = engineer_persona_dir / "history" / session_id
        engineer_session_dir.mkdir(parents=True)

        # Create root.json in engineer persona
        root_file = engineer_session_dir / "root.json"
        session_data = {
            "session_id": session_id,
            "parent_session_id": None,
            "model_spec": {"title": "test-model"},
            "usage": [],
            "messages": [
                {"role": "user", "content": "Only in engineer persona"},
            ],
            "thinking_mode": "off",
            "metadata": {
                "created_at": "2025-01-01T00:00:00Z",
                "last_updated": "2025-01-01T00:00:00Z",
                "root_dir": tmpdir,
                "cli_args": ["hdev"],
            },
        }

        with open(root_file, "w") as f:
            json.dump(session_data, f)

        # Create default persona directory (but no session)
        default_persona_dir.mkdir(parents=True)

        # Create a mock user interface and sandbox
        mock_ui = Mock(spec=UserInterface)
        mock_ui.permission_callback = Mock(return_value=True)
        mock_ui.permission_rendering_callback = Mock()
        sandbox = Sandbox(tmpdir, mode=SandboxMode.ALLOW_ALL)

        # Create a base context
        base_context = AgentContext(
            session_id="new-session",
            parent_session_id=None,
            model_spec={"title": "test-model"},
            sandbox=sandbox,
            user_interface=mock_ui,
            usage=[],
            memory_manager=Mock(),
            history_base_dir=default_persona_dir,
        )

        # Try to load the session from default persona directory (should fail)
        loaded_context = load_session_data(
            session_id, base_context, history_base_dir=default_persona_dir
        )

        # Verify the session was NOT found
        assert loaded_context is None, "Session should not be found in wrong persona"

        # Now try to load from the correct directory (should succeed)
        loaded_context = load_session_data(
            session_id, base_context, history_base_dir=engineer_persona_dir
        )

        # Verify the session WAS found
        assert loaded_context is not None, "Session should be found in correct persona"
        assert loaded_context.chat_history[0]["content"] == "Only in engineer persona"
