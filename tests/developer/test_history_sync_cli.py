"""Tests for history sync CLI commands."""

import os
from unittest.mock import Mock, patch

import pytest

from silica.developer.cli.history_sync import (
    list as list_sessions,
    status,
    sync,
)
from silica.developer.memory.proxy_config import MemoryProxyConfig


@pytest.fixture
def mock_config(tmp_path):
    """Create a mock config in a temporary directory."""
    config_path = tmp_path / "memory_proxy.json"
    with patch.object(MemoryProxyConfig, "DEFAULT_CONFIG_PATH", config_path):
        yield MemoryProxyConfig()


@pytest.fixture
def mock_persona(tmp_path):
    """Mock persona base directory with a history directory."""
    persona_dir = tmp_path / "personas" / "default"
    persona_dir.mkdir(parents=True)

    with patch("silica.developer.cli.history_sync.personas") as mock:
        persona_mock = Mock()
        persona_mock.base_directory = persona_dir
        mock.get_or_create.return_value = persona_mock
        yield mock, persona_dir


def test_list_command_no_sessions(mock_persona, capsys):
    """Test list command when no sessions exist."""
    mock, persona_dir = mock_persona
    list_sessions()

    captured = capsys.readouterr()
    assert "No history sessions found" in captured.out


def test_list_command_with_sessions(mock_persona, capsys):
    """Test list command with existing sessions."""
    mock, persona_dir = mock_persona

    # Create a history directory with sessions
    history_dir = persona_dir / "history"
    session1 = history_dir / "session-abc123"
    session2 = history_dir / "session-def456"
    session1.mkdir(parents=True)
    session2.mkdir(parents=True)

    # Add some files to the sessions
    (session1 / "conversation.json").write_text("{}")
    (session1 / "summary.md").write_text("# Summary")
    (session2 / "conversation.json").write_text("{}")

    # Mark session1 as synced
    (session1 / ".sync-index-history.json").write_text("{}")

    list_sessions()

    captured = capsys.readouterr()
    assert "session-abc123" in captured.out
    assert "session-def456" in captured.out
    assert "2" in captured.out  # session1 has 2 files
    assert "Synced" in captured.out


def test_status_command_session_not_found(mock_config, mock_persona, capsys):
    """Test status command when session doesn't exist."""
    mock, persona_dir = mock_persona
    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    status(session="nonexistent-session")

    captured = capsys.readouterr()
    assert "not found" in captured.out


def test_status_command_with_session(mock_config, mock_persona, capsys):
    """Test status command with existing session."""
    mock, persona_dir = mock_persona

    # Create session directory
    session_dir = persona_dir / "history" / "session-abc123"
    session_dir.mkdir(parents=True)
    (session_dir / "conversation.json").write_text("{}")

    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    status(session="session-abc123")

    captured = capsys.readouterr()
    assert "session-abc123" in captured.out
    assert "Configured" in captured.out
    assert "Local Files" in captured.out


def test_sync_command_not_configured(mock_config, mock_persona, capsys):
    """Test sync command when not configured."""
    mock, persona_dir = mock_persona

    sync(session="session-123")

    captured = capsys.readouterr()
    assert "not configured" in captured.out


def test_sync_command_session_not_found(mock_config, mock_persona, capsys):
    """Test sync command when session doesn't exist."""
    mock, persona_dir = mock_persona
    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    sync(session="nonexistent-session")

    captured = capsys.readouterr()
    assert "not found" in captured.out


def test_sync_command_dry_run(mock_config, mock_persona, capsys):
    """Test sync command with dry-run."""
    from silica.developer.memory.sync import SyncPlan, SyncOperationDetail

    mock, persona_dir = mock_persona

    # Create session directory
    session_dir = persona_dir / "history" / "session-abc123"
    session_dir.mkdir(parents=True)
    (session_dir / "conversation.json").write_text("{}")

    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    # Create a mock plan
    mock_plan = SyncPlan(
        upload=[
            SyncOperationDetail(
                type="upload",
                path="conversation.json",
                reason="New local file",
                local_size=1024,
            )
        ],
    )

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
        with patch("silica.developer.cli.history_sync.MemoryProxyClient"):
            with patch("silica.developer.cli.history_sync.SyncEngine") as MockEngine:
                mock_engine = MockEngine.return_value
                mock_engine.analyze_sync_operations.return_value = mock_plan
                with patch("silica.developer.cli.history_sync.LLMConflictResolver"):
                    sync(session="session-abc123", dry_run=True)

    captured = capsys.readouterr()
    # Check that sync plan is displayed
    assert "Sync Plan" in captured.out
    assert "Uploads" in captured.out
    assert "conversation.json" in captured.out


def test_sync_command_dry_run_no_changes(mock_config, mock_persona, capsys):
    """Test sync command with dry-run when everything is in sync."""
    from silica.developer.memory.sync import SyncPlan

    mock, persona_dir = mock_persona

    # Create session directory
    session_dir = persona_dir / "history" / "session-abc123"
    session_dir.mkdir(parents=True)
    (session_dir / "conversation.json").write_text("{}")

    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    # Empty plan = everything in sync
    mock_plan = SyncPlan()

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
        with patch("silica.developer.cli.history_sync.MemoryProxyClient"):
            with patch("silica.developer.cli.history_sync.SyncEngine") as MockEngine:
                mock_engine = MockEngine.return_value
                mock_engine.analyze_sync_operations.return_value = mock_plan
                with patch("silica.developer.cli.history_sync.LLMConflictResolver"):
                    sync(session="session-abc123", dry_run=True)

    captured = capsys.readouterr()
    # Check that "in sync" message is displayed
    assert "in sync" in captured.out.lower() or "no operations" in captured.out.lower()


def test_sync_command_dry_run_with_conflicts(mock_config, mock_persona, capsys):
    """Test sync command with dry-run showing conflicts."""
    from silica.developer.memory.sync import SyncPlan, SyncOperationDetail

    mock, persona_dir = mock_persona

    # Create session directory
    session_dir = persona_dir / "history" / "session-abc123"
    session_dir.mkdir(parents=True)
    (session_dir / "conversation.json").write_text("{}")

    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    # Create a mock plan with conflicts
    mock_plan = SyncPlan(
        conflicts=[
            SyncOperationDetail(
                type="conflict",
                path="conversation.json",
                reason="Both local and remote modified since last sync",
            )
        ],
    )

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
        with patch("silica.developer.cli.history_sync.MemoryProxyClient"):
            with patch("silica.developer.cli.history_sync.SyncEngine") as MockEngine:
                mock_engine = MockEngine.return_value
                mock_engine.analyze_sync_operations.return_value = mock_plan
                with patch("silica.developer.cli.history_sync.LLMConflictResolver"):
                    sync(session="session-abc123", dry_run=True)

    captured = capsys.readouterr()
    # Check that conflicts are displayed
    assert "Conflicts" in captured.out
    assert "conversation.json" in captured.out
    assert "LLM merge" in captured.out


def test_sync_command_success(mock_config, mock_persona, capsys):
    """Test sync command with successful sync."""
    mock, persona_dir = mock_persona

    # Create session directory
    session_dir = persona_dir / "history" / "session-abc123"
    session_dir.mkdir(parents=True)
    (session_dir / "conversation.json").write_text("{}")

    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
        with patch("silica.developer.cli.history_sync.MemoryProxyClient"):
            with patch("silica.developer.cli.history_sync.SyncEngine"):
                with patch("silica.developer.cli.history_sync.LLMConflictResolver"):
                    with patch(
                        "silica.developer.cli.history_sync.sync_with_retry"
                    ) as mock_sync:
                        # Create a mock result
                        mock_result = Mock()
                        mock_result.succeeded = [Mock(type="upload", path="test.md")]
                        mock_result.failed = []
                        mock_result.conflicts = []
                        mock_result.skipped = []
                        mock_result.duration = 1.5
                        mock_sync.return_value = mock_result

                        sync(session="session-abc123")

                        captured = capsys.readouterr()
                        assert "Sync completed" in captured.out
                        assert "Succeeded: 1" in captured.out


def test_sync_command_with_failures(mock_config, mock_persona, capsys):
    """Test sync command with failures."""
    mock, persona_dir = mock_persona

    # Create session directory
    session_dir = persona_dir / "history" / "session-abc123"
    session_dir.mkdir(parents=True)
    (session_dir / "conversation.json").write_text("{}")

    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
        with patch("silica.developer.cli.history_sync.MemoryProxyClient"):
            with patch("silica.developer.cli.history_sync.SyncEngine"):
                with patch("silica.developer.cli.history_sync.LLMConflictResolver"):
                    with patch(
                        "silica.developer.cli.history_sync.sync_with_retry"
                    ) as mock_sync:
                        # Create a mock result with failures
                        mock_result = Mock()
                        mock_result.succeeded = []
                        mock_result.failed = [Mock(type="upload", path="test.md")]
                        mock_result.conflicts = []
                        mock_result.skipped = []
                        mock_result.duration = 1.5
                        mock_sync.return_value = mock_result

                        sync(session="session-abc123")

                        captured = capsys.readouterr()
                        assert "Sync completed" in captured.out
                        assert "Failed: 1" in captured.out
                        assert "Failed operations" in captured.out
