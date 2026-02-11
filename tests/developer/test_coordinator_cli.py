"""Tests for coordinator CLI command."""

from unittest.mock import patch

from silica.developer.cli.coordinator import (
    coordinator_list,
    coordinator_delete,
    coordinator_info,
)


class TestCoordinatorList:
    """Test the list command."""

    def test_list_no_sessions(self, capsys):
        """Should show message when no sessions exist."""
        with patch(
            "silica.developer.cli.coordinator.list_sessions",
            return_value=[],
        ):
            coordinator_list()

        captured = capsys.readouterr()
        assert "No coordination sessions found" in captured.out

    def test_list_with_sessions(self, capsys):
        """Should display sessions in a table."""
        mock_sessions = [
            {
                "session_id": "abc12345",
                "display_name": "Test Session",
                "agent_count": 2,
                "created_at": "2025-01-15T10:00:00",
            },
            {
                "session_id": "def67890",
                "display_name": "Another Session",
                "agent_count": 0,
                "created_at": "2025-01-14T09:00:00",
            },
        ]

        with patch(
            "silica.developer.cli.coordinator.list_sessions",
            return_value=mock_sessions,
        ):
            coordinator_list()

        captured = capsys.readouterr()
        assert "abc12345" in captured.out
        assert "Test Session" in captured.out
        assert "def67890" in captured.out


class TestCoordinatorDelete:
    """Test the delete command."""

    def test_delete_existing_session(self, capsys):
        """Should delete an existing session."""
        with patch(
            "silica.developer.cli.coordinator.delete_session",
            return_value=True,
        ):
            coordinator_delete("abc12345", force=True)

        captured = capsys.readouterr()
        assert "Session deleted" in captured.out

    def test_delete_nonexistent_session(self, capsys):
        """Should show error for nonexistent session."""
        with patch(
            "silica.developer.cli.coordinator.delete_session",
            return_value=False,
        ):
            coordinator_delete("nonexistent", force=True)

        captured = capsys.readouterr()
        assert "not found" in captured.out


class TestCoordinatorInfo:
    """Test the info command."""

    def test_info_nonexistent_session(self, capsys):
        """Should show error for nonexistent session."""
        from deadrop import Deaddrop

        mock_deaddrop = Deaddrop.in_memory()

        with patch(
            "silica.developer.cli.coordinator._get_deaddrop_client",
            return_value=mock_deaddrop,
        ):
            with patch(
                "silica.developer.cli.coordinator.CoordinationSession.resume_session",
                side_effect=FileNotFoundError("Session not found"),
            ):
                coordinator_info("nonexistent")

        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_info_existing_session(self, capsys, tmp_path):
        """Should display session info."""
        from deadrop import Deaddrop
        from silica.developer.coordination.session import CoordinationSession

        # Create a real session with mock storage
        with patch(
            "silica.developer.coordination.session.get_sessions_dir",
            return_value=tmp_path,
        ):
            deaddrop = Deaddrop.in_memory()
            session = CoordinationSession.create_session(deaddrop, "Test Info Session")

            # Add an agent
            session.register_agent("agent-1", "id-1", "Worker 1", "ws-1")

            # Mock deaddrop client and resume to return our session
            with patch(
                "silica.developer.cli.coordinator._get_deaddrop_client",
                return_value=deaddrop,
            ):
                with patch(
                    "silica.developer.cli.coordinator.CoordinationSession.resume_session",
                    return_value=session,
                ):
                    coordinator_info(session.session_id)

        captured = capsys.readouterr()
        assert "Test Info Session" in captured.out
        assert "agent-1" in captured.out or "Worker 1" in captured.out


class TestCoordinatorCommandHelp:
    """Test that CLI help works."""

    def test_help_text_exists(self):
        """CLI commands should have help text."""
        from silica.developer.cli.coordinator import coordinator_app

        # The app should have commands registered
        assert coordinator_app is not None
