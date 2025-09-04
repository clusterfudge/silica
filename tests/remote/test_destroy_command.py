"""Tests for the destroy command functionality."""

import shutil
import tempfile
from pathlib import Path
import yaml
import pytest
from unittest.mock import patch, MagicMock

from silica.remote.cli.commands.destroy import destroy
from silica.remote.utils.piku import get_app_name


class TestDestroyCommand:
    """Test class for destroy command functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def mock_git_repo(self, temp_dir):
        """Create a mock git repository structure."""
        # Create .git directory to simulate a git repo
        git_dir = temp_dir / ".git"
        git_dir.mkdir()

        # Create .silica directory
        silica_dir = temp_dir / ".silica"
        silica_dir.mkdir()

        return temp_dir

    @pytest.fixture
    def multi_workspace_config(self, mock_git_repo):
        """Create a multi-workspace configuration."""
        silica_dir = mock_git_repo / ".silica"

        # Create a config with multiple workspaces
        config = {
            "default_workspace": "second",
            "workspaces": {
                "agent": {
                    "piku_connection": "piku",
                    "app_name": "agent-silica",
                    "branch": "main",
                },
                "second": {
                    "piku_connection": "piku",
                    "app_name": "second-silica",
                    "branch": "main",
                },
            },
        }

        # Write the config file
        config_file = silica_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        return mock_git_repo

    @patch("silica.remote.utils.piku.find_git_root")
    @patch("silica.remote.utils.piku.get_silica_dir")
    def test_get_app_name_uses_correct_workspace(
        self, mock_get_silica_dir, mock_find_git_root, multi_workspace_config
    ):
        """Test that get_app_name returns the correct app name for the specified workspace."""
        git_root = multi_workspace_config
        silica_dir = git_root / ".silica"

        # Mock the required functions
        mock_find_git_root.return_value = git_root
        mock_get_silica_dir.return_value = silica_dir

        # Test getting app name for default workspace (second)
        app_name_default = get_app_name(git_root)
        assert (
            app_name_default == "second-silica"
        ), "Should use default workspace 'second'"

        # Test getting app name for specific workspace (agent)
        app_name_agent = get_app_name(git_root, workspace_name="agent")
        assert (
            app_name_agent == "agent-silica"
        ), "Should use specified workspace 'agent'"

        # Test getting app name for specific workspace (second)
        app_name_second = get_app_name(git_root, workspace_name="second")
        assert (
            app_name_second == "second-silica"
        ), "Should use specified workspace 'second'"

    @patch("silica.remote.cli.commands.destroy.piku_utils.run_piku_in_silica")
    @patch("silica.remote.cli.commands.destroy.get_antennae_client")
    @patch("silica.remote.cli.commands.destroy.is_local_workspace_for_cleanup")
    @patch("silica.remote.cli.commands.destroy.Confirm.ask")
    @patch("silica.remote.cli.commands.destroy.find_git_root")
    @patch("silica.remote.cli.commands.destroy.get_silica_dir")
    def test_destroy_command_uses_specified_workspace(
        self,
        mock_get_silica_dir,
        mock_find_git_root,
        mock_confirm,
        mock_is_local,
        mock_get_client,
        mock_run_piku,
        multi_workspace_config,
    ):
        """Test that destroy command uses HTTP client for the specified workspace."""
        # Setup mocks
        git_root = multi_workspace_config
        silica_dir = git_root / ".silica"

        mock_find_git_root.return_value = git_root
        mock_get_silica_dir.return_value = silica_dir
        mock_confirm.return_value = True  # User confirms destruction
        mock_is_local.return_value = False  # Remote workspace
        mock_run_piku.return_value = MagicMock(stdout="", returncode=0)

        # Mock HTTP client
        mock_client = MagicMock()
        mock_client.destroy.return_value = (
            True,
            {"success": True, "message": "Destroyed"},
        )
        mock_get_client.return_value = mock_client

        # Call destroy function directly with parameters
        destroy(workspace="agent", force=True, all=False)

        # Verify that get_antennae_client was called with the correct workspace
        mock_get_client.assert_called_with(silica_dir, "agent")

        # Verify that HTTP destroy was called
        mock_client.destroy.assert_called_once()

        # Verify workspace type check was called
        mock_is_local.assert_called_with(silica_dir, "agent")

    @patch("silica.remote.cli.commands.destroy.piku_utils.run_piku_in_silica")
    @patch("silica.remote.cli.commands.destroy.get_antennae_client")
    @patch("silica.remote.cli.commands.destroy.is_local_workspace_for_cleanup")
    @patch("silica.remote.cli.commands.destroy.Confirm.ask")
    @patch("silica.remote.cli.commands.destroy.find_git_root")
    @patch("silica.remote.cli.commands.destroy.get_silica_dir")
    def test_destroy_command_default_workspace_consistency(
        self,
        mock_get_silica_dir,
        mock_find_git_root,
        mock_confirm,
        mock_is_local,
        mock_get_client,
        mock_run_piku,
        multi_workspace_config,
    ):
        """Test that destroy command uses HTTP client for default workspace."""
        # Setup mocks
        git_root = multi_workspace_config
        silica_dir = git_root / ".silica"

        mock_find_git_root.return_value = git_root
        mock_get_silica_dir.return_value = silica_dir
        mock_confirm.return_value = True  # User confirms destruction
        mock_is_local.return_value = True  # Local workspace
        mock_run_piku.return_value = MagicMock(stdout="", returncode=0)

        # Mock HTTP client
        mock_client = MagicMock()
        mock_client.destroy.return_value = (
            True,
            {"success": True, "message": "Destroyed"},
        )
        mock_get_client.return_value = mock_client

        # Call destroy function with default workspace "agent"
        destroy(force=True, workspace="agent", all=False)

        # Verify that get_antennae_client was called with the default workspace
        mock_get_client.assert_called_with(silica_dir, "agent")

        # Verify that HTTP destroy was called
        mock_client.destroy.assert_called_once()

        # Verify local workspace check was called
        mock_is_local.assert_called_with(silica_dir, "agent")
