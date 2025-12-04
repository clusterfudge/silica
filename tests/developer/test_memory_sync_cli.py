"""Tests for memory sync CLI commands."""

import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from silica.developer.cli.memory_sync import (
    setup,
    enable,
    disable,
    status,
    test,
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
def mock_persona():
    """Mock persona base directory."""
    with patch("silica.developer.cli.memory_sync.personas") as mock:
        persona_mock = Mock()
        persona_mock.base_directory = Path("/tmp/test-persona")
        mock.get_or_create.return_value = persona_mock
        yield mock


def test_setup_command(tmp_path, capsys):
    """Test setup command."""
    config_path = tmp_path / "memory_proxy.json"
    with patch.object(MemoryProxyConfig, "DEFAULT_CONFIG_PATH", config_path):
        setup(url="https://memory.example.com", token="test_token_123")

        # Reload config to verify it was saved
        config = MemoryProxyConfig()
        assert config.remote_url == "https://memory.example.com"
        assert config.auth_token == "test_token_123"
        assert config.is_globally_enabled is True

        # Check output
        captured = capsys.readouterr()
        assert "configured successfully" in captured.out


def test_setup_command_no_enable(tmp_path, capsys):
    """Test setup command with --no-enable."""
    config_path = tmp_path / "memory_proxy.json"
    with patch.object(MemoryProxyConfig, "DEFAULT_CONFIG_PATH", config_path):
        setup(url="https://memory.example.com", token="test_token_123", enable=False)

        # Reload config to verify it was saved but not enabled
        config = MemoryProxyConfig()
        assert config.remote_url == "https://memory.example.com"
        assert config.auth_token == "test_token_123"
        assert config.is_globally_enabled is False


def test_enable_command_global(tmp_path, capsys):
    """Test enable command globally."""
    config_path = tmp_path / "memory_proxy.json"
    with patch.object(MemoryProxyConfig, "DEFAULT_CONFIG_PATH", config_path):
        # Setup first
        config = MemoryProxyConfig()
        config.setup("https://memory.example.com", "test_token", enable=False)

        enable()

        # Reload to verify
        config = MemoryProxyConfig()
        assert config.is_globally_enabled is True

        captured = capsys.readouterr()
        assert "enabled globally" in captured.out


def test_enable_command_persona(mock_config, capsys):
    """Test enable command for specific persona."""
    # Setup first
    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    enable(persona="test_persona")

    assert mock_config.is_persona_enabled("test_persona") is True

    captured = capsys.readouterr()
    assert "test_persona" in captured.out


def test_enable_command_not_configured(mock_config, capsys):
    """Test enable command when not configured."""
    enable()

    captured = capsys.readouterr()
    assert "not configured" in captured.out


def test_disable_command_global(tmp_path, capsys):
    """Test disable command globally."""
    config_path = tmp_path / "memory_proxy.json"
    with patch.object(MemoryProxyConfig, "DEFAULT_CONFIG_PATH", config_path):
        # Setup first
        config = MemoryProxyConfig()
        config.setup("https://memory.example.com", "test_token", enable=True)

        disable()

        # Reload to verify
        config = MemoryProxyConfig()
        assert config.is_globally_enabled is False

        captured = capsys.readouterr()
        assert "disabled globally" in captured.out


def test_disable_command_persona(tmp_path, capsys):
    """Test disable command for specific persona."""
    config_path = tmp_path / "memory_proxy.json"
    with patch.object(MemoryProxyConfig, "DEFAULT_CONFIG_PATH", config_path):
        # Setup first
        config = MemoryProxyConfig()
        config.setup("https://memory.example.com", "test_token", enable=True)

        disable(persona="test_persona")

        # Reload to verify
        config = MemoryProxyConfig()
        assert config.is_persona_enabled("test_persona") is False

        captured = capsys.readouterr()
        assert "test_persona" in captured.out


def test_status_command_not_configured(mock_config, mock_persona, capsys):
    """Test status command when not configured."""
    status()

    captured = capsys.readouterr()
    assert "Configured" in captured.out
    assert "✗ No" in captured.out


def test_status_command_configured(mock_config, mock_persona, capsys):
    """Test status command when configured."""
    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    status()

    captured = capsys.readouterr()
    assert "Configured" in captured.out
    assert "✓ Yes" in captured.out
    assert "memory.example.com" in captured.out


def test_status_command_with_last_sync(mock_config, mock_persona, capsys):
    """Test status command with last sync timestamp."""
    from datetime import datetime, timezone

    mock_config.setup("https://memory.example.com", "test_token", enable=True)
    mock_config.set_last_sync("default", datetime.now(timezone.utc))

    status()

    captured = capsys.readouterr()
    assert "Last Sync" in captured.out
    assert "seconds ago" in captured.out or "minutes ago" in captured.out


def test_test_command_not_configured(mock_config, capsys):
    """Test test command when not configured."""
    test()

    captured = capsys.readouterr()
    assert "not configured" in captured.out


def test_test_command_success(mock_config, capsys):
    """Test test command with successful connection."""
    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    with patch("silica.developer.cli.memory_sync.MemoryProxyClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.health_check.return_value = True

        test()

        captured = capsys.readouterr()
        assert "Connection successful" in captured.out


def test_test_command_failure(mock_config, capsys):
    """Test test command with failed connection."""
    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    with patch("silica.developer.cli.memory_sync.MemoryProxyClient") as MockClient:
        mock_client = MockClient.return_value
        mock_client.health_check.return_value = False

        test()

        captured = capsys.readouterr()
        assert "Connection failed" in captured.out


def test_test_command_exception(mock_config, capsys):
    """Test test command with exception."""
    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    with patch("silica.developer.cli.memory_sync.MemoryProxyClient") as MockClient:
        MockClient.return_value.health_check.side_effect = Exception("Network error")

        test()

        captured = capsys.readouterr()
        assert "Connection failed" in captured.out
        assert "Network error" in captured.out


def test_sync_command_not_configured(mock_config, mock_persona, capsys):
    """Test sync command when not configured."""
    sync()

    captured = capsys.readouterr()
    assert "not configured" in captured.out


def test_sync_command_not_enabled(mock_config, mock_persona, capsys):
    """Test sync command when sync is disabled."""
    mock_config.setup("https://memory.example.com", "test_token", enable=False)

    sync()

    captured = capsys.readouterr()
    assert "disabled" in captured.out


def test_sync_command_dry_run(tmp_path, mock_persona, capsys):
    """Test sync command with dry-run."""
    from silica.developer.memory.sync import SyncPlan, SyncOperationDetail

    config_path = tmp_path / "memory_proxy.json"
    with patch.object(MemoryProxyConfig, "DEFAULT_CONFIG_PATH", config_path):
        config = MemoryProxyConfig()
        config.setup("https://memory.example.com", "test_token", enable=True)

        # Create a mock plan
        mock_plan = SyncPlan(
            upload=[
                SyncOperationDetail(
                    type="upload", path="test.md", reason="New local file"
                )
            ],
            download=[
                SyncOperationDetail(
                    type="download", path="remote.md", reason="New remote file"
                )
            ],
        )

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
            with patch("silica.developer.cli.memory_sync.MemoryProxyClient"):
                with patch("silica.developer.cli.memory_sync.SyncEngine") as MockEngine:
                    mock_engine = MockEngine.return_value
                    mock_engine.analyze_sync_operations.return_value = mock_plan
                    with patch("silica.developer.cli.memory_sync.LLMConflictResolver"):
                        sync(dry_run=True)

        captured = capsys.readouterr()
        # Check that sync plan is displayed
        assert "Sync Plan" in captured.out
        assert "Uploads" in captured.out
        assert "Downloads" in captured.out
        assert "test.md" in captured.out
        assert "remote.md" in captured.out


def test_sync_command_dry_run_no_changes(tmp_path, mock_persona, capsys):
    """Test sync command with dry-run when everything is in sync."""
    from silica.developer.memory.sync import SyncPlan

    config_path = tmp_path / "memory_proxy.json"
    with patch.object(MemoryProxyConfig, "DEFAULT_CONFIG_PATH", config_path):
        config = MemoryProxyConfig()
        config.setup("https://memory.example.com", "test_token", enable=True)

        # Empty plan = everything in sync
        mock_plan = SyncPlan()

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
            with patch("silica.developer.cli.memory_sync.MemoryProxyClient"):
                with patch("silica.developer.cli.memory_sync.SyncEngine") as MockEngine:
                    mock_engine = MockEngine.return_value
                    mock_engine.analyze_sync_operations.return_value = mock_plan
                    with patch("silica.developer.cli.memory_sync.LLMConflictResolver"):
                        sync(dry_run=True)

        captured = capsys.readouterr()
        # Check that "in sync" message is displayed
        assert (
            "in sync" in captured.out.lower() or "no operations" in captured.out.lower()
        )


def test_sync_command_success(tmp_path, mock_persona, capsys):
    """Test sync command with successful sync."""
    config_path = tmp_path / "memory_proxy.json"
    with patch.object(MemoryProxyConfig, "DEFAULT_CONFIG_PATH", config_path):
        config = MemoryProxyConfig()
        config.setup("https://memory.example.com", "test_token", enable=True)

        # Mock the sync components
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
            with patch("silica.developer.cli.memory_sync.MemoryProxyClient"):
                with patch("silica.developer.cli.memory_sync.SyncEngine"):
                    with patch("silica.developer.cli.memory_sync.LLMConflictResolver"):
                        with patch(
                            "silica.developer.cli.memory_sync.sync_with_retry"
                        ) as mock_sync:
                            # Create a mock result
                            mock_result = Mock()
                            mock_result.succeeded = [
                                Mock(type="upload", path="test.md")
                            ]
                            mock_result.failed = []
                            mock_result.conflicts = []
                            mock_result.skipped = []
                            mock_result.duration = 1.5
                            mock_sync.return_value = mock_result

                            sync()

                            captured = capsys.readouterr()
                            assert "Sync completed" in captured.out
                            assert "Succeeded: 1" in captured.out


def test_sync_command_with_failures(tmp_path, mock_persona, capsys):
    """Test sync command with failures."""
    config_path = tmp_path / "memory_proxy.json"
    with patch.object(MemoryProxyConfig, "DEFAULT_CONFIG_PATH", config_path):
        config = MemoryProxyConfig()
        config.setup("https://memory.example.com", "test_token", enable=True)

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
            with patch("silica.developer.cli.memory_sync.MemoryProxyClient"):
                with patch("silica.developer.cli.memory_sync.SyncEngine"):
                    with patch("silica.developer.cli.memory_sync.LLMConflictResolver"):
                        with patch(
                            "silica.developer.cli.memory_sync.sync_with_retry"
                        ) as mock_sync:
                            # Create a mock result with failures
                            mock_result = Mock()
                            mock_result.succeeded = []
                            mock_result.failed = [Mock(type="upload", path="test.md")]
                            mock_result.conflicts = []
                            mock_result.skipped = []
                            mock_result.duration = 1.5
                            mock_sync.return_value = mock_result

                            sync()

                            captured = capsys.readouterr()
                            assert "Sync completed" in captured.out
                            assert "Failed: 1" in captured.out
                            assert "Failed operations" in captured.out


def test_sync_command_without_anthropic_key(mock_config, mock_persona, capsys):
    """Test sync command without ANTHROPIC_API_KEY."""
    mock_config.setup("https://memory.example.com", "test_token", enable=True)

    # Make sure ANTHROPIC_API_KEY is not set
    with patch.dict(os.environ, {}, clear=True):
        with patch("silica.developer.cli.memory_sync.MemoryProxyClient"):
            with patch("silica.developer.cli.memory_sync.SyncEngine"):
                with patch(
                    "silica.developer.cli.memory_sync.sync_with_retry"
                ) as mock_sync:
                    mock_result = Mock()
                    mock_result.succeeded = []
                    mock_result.failed = []
                    mock_result.conflicts = []
                    mock_result.skipped = []
                    mock_result.duration = 1.5
                    mock_sync.return_value = mock_result

                    sync()

                    captured = capsys.readouterr()
                    assert "ANTHROPIC_API_KEY not set" in captured.out
