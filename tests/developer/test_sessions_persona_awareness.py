"""Test that /sessions and /resume commands are persona-aware."""

from pathlib import Path
from unittest.mock import Mock, patch
from silica.developer.toolbox import Toolbox
from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox


def test_sessions_command_uses_context_persona(tmp_path):
    """Test that the /sessions command uses the persona from the context."""
    # Create a mock context with a specific persona directory
    persona_dir = tmp_path / "test_persona"
    persona_dir.mkdir()

    mock_context = Mock(spec=AgentContext)
    mock_context.history_base_dir = persona_dir
    mock_context.sandbox = Mock(spec=Sandbox)
    mock_context.user_interface = Mock()

    # Create toolbox with the mock context
    toolbox = Toolbox(mock_context)

    # Mock the list_sessions function to verify it receives the correct parameters
    with patch("silica.developer.toolbox.list_sessions") as mock_list_sessions:
        mock_list_sessions.return_value = []

        # Call the sessions command
        toolbox._list_sessions(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )

        # Verify list_sessions was called with the correct history_base_dir
        mock_list_sessions.assert_called_once_with(
            None,  # workdir
            history_base_dir=persona_dir,
        )


def test_resume_command_uses_context_persona(tmp_path):
    """Test that the /resume command uses the persona from the context."""
    # Create a mock context with a specific persona directory
    persona_dir = tmp_path / "test_persona"
    persona_dir.mkdir()

    mock_context = Mock(spec=AgentContext)
    mock_context.history_base_dir = persona_dir
    mock_context.sandbox = Mock(spec=Sandbox)
    mock_context.user_interface = Mock()

    # Create toolbox with the mock context
    toolbox = Toolbox(mock_context)

    # Mock the resume_session function to verify it receives the correct parameters
    with patch("silica.developer.toolbox.resume_session") as mock_resume:
        mock_resume.return_value = True

        # Call the resume command
        toolbox._resume_session(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="test-session-123",
        )

        # Verify resume_session was called with the correct history_base_dir
        mock_resume.assert_called_once_with(
            "test-session-123", history_base_dir=persona_dir
        )


def test_sessions_command_handles_workdir_filter(tmp_path):
    """Test that the /sessions command properly handles workdir filtering."""
    persona_dir = tmp_path / "test_persona"
    persona_dir.mkdir()

    mock_context = Mock(spec=AgentContext)
    mock_context.history_base_dir = persona_dir
    mock_context.sandbox = Mock(spec=Sandbox)
    mock_context.user_interface = Mock()

    toolbox = Toolbox(mock_context)

    with patch("silica.developer.toolbox.list_sessions") as mock_list_sessions:
        mock_list_sessions.return_value = []

        # Call with workdir filter
        toolbox._list_sessions(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="/path/to/project",
        )

        # Verify list_sessions was called with both workdir and history_base_dir
        mock_list_sessions.assert_called_once_with(
            "/path/to/project", history_base_dir=persona_dir
        )


def test_sessions_command_defaults_to_none_when_no_persona(tmp_path):
    """Test that /sessions handles missing history_base_dir gracefully."""
    mock_context = Mock(spec=AgentContext)
    # Set history_base_dir to None explicitly
    mock_context.history_base_dir = None
    mock_context.sandbox = Mock(spec=Sandbox)
    mock_context.user_interface = Mock()

    toolbox = Toolbox(mock_context)

    with patch("silica.developer.toolbox.list_sessions") as mock_list_sessions:
        mock_list_sessions.return_value = []

        toolbox._list_sessions(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",
        )

        # Should pass None as history_base_dir (will use default)
        mock_list_sessions.assert_called_once_with(None, history_base_dir=None)


def test_resume_command_handles_empty_session_id():
    """Test that /resume handles empty session ID gracefully."""
    mock_context = Mock(spec=AgentContext)
    mock_context.history_base_dir = Path("/tmp/test")
    mock_context.sandbox = Mock(spec=Sandbox)
    mock_context.user_interface = Mock()

    toolbox = Toolbox(mock_context)

    with patch("silica.developer.toolbox.resume_session") as mock_resume:
        result = toolbox._resume_session(
            user_interface=mock_context.user_interface,
            sandbox=mock_context.sandbox,
            user_input="",  # Empty session ID
        )

        # Should not call resume_session
        mock_resume.assert_not_called()

        # Should return error message
        assert "Error" in result
        assert "No session ID" in result
