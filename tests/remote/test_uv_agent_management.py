#!/usr/bin/env python3
"""Tests for UV-based agent management."""

import pytest
import tempfile
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add silica to path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

# agent_yaml module removed - using hardcoded agent configuration for tests
from silica.remote.cli.commands.workspace_environment import (
    install_agent,
    is_agent_installed,
)


# Mock AgentConfig for testing since the original class is deleted
class AgentConfig:
    def __init__(
        self,
        name,
        description,
        install_commands,
        fallback_install_commands,
        check_command,
        launch_command,
        default_args,
        dependencies,
        required_env_vars,
        recommended_env_vars,
    ):
        self.name = name
        self.description = description
        self.install_commands = install_commands
        self.fallback_install_commands = fallback_install_commands
        self.check_command = check_command
        self.launch_command = launch_command
        self.default_args = default_args
        self.dependencies = dependencies
        self.required_env_vars = required_env_vars
        self.recommended_env_vars = recommended_env_vars


class TestUVAgentManagement:
    """Test UV-based agent installation and management."""

    def test_agent_installation_directory_context(self):
        """Test that agent installation works from project root directory."""
        # Create a mock agent config dict (silica developer style)
        agent_config = {
            "name": "silica_developer",
            "description": "Silica Developer agent",
            "install": {
                "commands": ["uv add silica"],
                "fallback_commands": ["pip install silica"],
                "check_command": "silica --help",
            },
        }

        # Test installation with mocked subprocess
        with patch("subprocess.run") as mock_run:
            with patch(
                "silica.remote.cli.commands.workspace_environment.is_agent_installed"
            ) as mock_installed:
                # Mock not installed initially, then installed after sync
                mock_installed.side_effect = [False, True]
                # Mock successful uv sync (which now handles installation)
                mock_run.return_value = MagicMock(returncode=0)

                result = install_agent(agent_config)
                assert result is True

                # Verify uv sync was attempted (new installation method)
                mock_run.assert_called()
                call_args = str(mock_run.call_args_list)
                assert "uv" in call_args and "sync" in call_args

    def test_agent_check_with_uv_run(self):
        """Test that agent check works with uv run when direct command fails."""
        agent_config = {
            "name": "silica_developer",
            "description": "Silica Developer agent",
            "install": {
                "commands": ["uv add silica"],
                "fallback_commands": [],
                "check_command": "silica --help",
            },
        }

        with patch("subprocess.run") as mock_run:
            # First call (direct command) fails, second call (uv run) succeeds
            mock_run.side_effect = [
                MagicMock(returncode=1),  # Direct command fails
                MagicMock(returncode=0),  # uv run succeeds
            ]

            result = is_agent_installed(agent_config)
            assert result is True

            # Verify both calls were made
            assert mock_run.call_count == 2

            # Verify the second call used uv run
            second_call = mock_run.call_args_list[1]
            call_args = second_call[0][0]
            assert call_args[:2] == ["uv", "run"]

    def test_fallback_to_pip_when_uv_fails(self):
        """Test that installation falls back to pip when uv fails."""
        agent_config = {
            "name": "silica_developer",
            "description": "Silica Developer agent",
            "install": {
                "commands": ["uv add silica"],
                "fallback_commands": ["pip install silica"],
                "check_command": "silica --help",
            },
        }

        with patch("subprocess.run") as mock_run:
            with patch(
                "silica.remote.cli.commands.workspace_environment.is_agent_installed"
            ) as mock_installed:
                # Mock not installed throughout (force fallback path)
                mock_installed.side_effect = [False, False, False, True]

                # Mock: uv sync fails, fallback commands succeed
                mock_run.side_effect = [
                    MagicMock(returncode=1, stderr="uv sync failed"),  # uv sync fails
                    MagicMock(returncode=1, stderr="uv add failed"),  # uv add fails
                    MagicMock(returncode=0),  # pip install succeeds
                ]

                result = install_agent(agent_config)
                assert result is True

                # Verify fallback commands were tried
                assert mock_run.call_count >= 2

    def test_workspace_directory_structure(self):
        """Test that the agent runner stays in project root, not code directory."""
        # This test would be integration-level, but we can test the concept
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir) / "test-workspace"
            workspace_dir.mkdir()

            # Create project structure
            (workspace_dir / "pyproject.toml").write_text("[project]\nname='test'\n")
            (workspace_dir / "code").mkdir()

            original_dir = os.getcwd()
            try:
                os.chdir(workspace_dir)

                # Verify we can run uv commands from project root
                result = subprocess.run(
                    ["uv", "--version"], capture_output=True, text=True
                )
                assert result.returncode == 0

                # Verify code directory exists but we don't need to be in it
                assert (workspace_dir / "code").exists()
                # Use resolved paths to handle symlink differences on macOS
                assert Path(os.getcwd()).resolve() == workspace_dir.resolve()

            finally:
                os.chdir(original_dir)

    def test_executable_resolution_workflow(self):
        """Test the basic agent launch command generation (resolve_agent_executable_path removed)."""
        # Import the function we want to test from workspace_environment
        from silica.remote.cli.commands.workspace_environment import (
            generate_launch_command,
        )

        # Create agent config dict (hardcoded silica developer style)
        agent_config = {
            "name": "silica_developer",
            "description": "Silica Developer agent",
            "launch": {
                "command": "uv run silica developer",
                "default_args": ["--dwr", "--persona", "autonomous_engineer"],
            },
        }

        workspace_config = {"agent_config": {"flags": [], "args": {}}}

        # Test command generation
        result = generate_launch_command(agent_config, workspace_config)

        # Should return the hardcoded silica developer command
        assert "uv run silica developer" in result
        assert "--dwr" in result
        assert "autonomous_engineer" in result


if __name__ == "__main__":
    pytest.main([__file__])

    def test_workspace_directory_structure(self):
        """Test that the agent installation works from project root, execution from code dir."""
        # This test would be integration-level, but we can test the concept
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir) / "test-workspace"
            workspace_dir.mkdir()

            # Create project structure
            (workspace_dir / "pyproject.toml").write_text("[project]\nname='test'\n")
            code_dir = workspace_dir / "code"
            code_dir.mkdir()

            original_dir = os.getcwd()
            try:
                # Test installation from project root
                os.chdir(workspace_dir)

                # Verify we can run uv commands from project root
                result = subprocess.run(
                    ["uv", "--version"], capture_output=True, text=True
                )
                assert result.returncode == 0

                # Verify code directory exists for agent execution
                assert code_dir.exists()

                # Test that we can change to code directory after installation
                os.chdir(code_dir)
                assert Path(os.getcwd()).resolve() == code_dir.resolve()

            finally:
                os.chdir(original_dir)
