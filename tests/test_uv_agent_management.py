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

from silica.utils.agent_yaml import AgentConfig, install_agent, is_agent_installed


class TestUVAgentManagement:
    """Test UV-based agent installation and management."""

    def test_uv_add_in_agent_config(self):
        """Test that agent configs use uv add as primary installation method."""
        from silica.utils.agent_yaml import load_agent_config

        # Test hdev config
        hdev_config = load_agent_config("hdev")
        assert hdev_config is not None
        assert "uv add heare-developer" in hdev_config.install_commands
        assert hdev_config.install_commands[0] == "uv add heare-developer"

        # Test aider config
        aider_config = load_agent_config("aider")
        assert aider_config is not None
        assert "uv add aider-chat" in aider_config.install_commands
        assert aider_config.install_commands[0] == "uv add aider-chat"

    def test_agent_installation_directory_context(self):
        """Test that agent installation works from project root directory."""
        # Create a mock agent config that uses uv add
        agent_config = AgentConfig(
            name="test-agent",
            description="Test agent",
            install_commands=["uv add requests"],
            fallback_install_commands=["pip install requests"],
            check_command="python -c 'import requests'",
            launch_command="uv run python",
            default_args=[],
            dependencies=["requests"],
            required_env_vars=[],
            recommended_env_vars=[],
        )

        # Test installation with mocked subprocess
        with patch("subprocess.run") as mock_run:
            with patch("silica.utils.agent_yaml.is_agent_installed") as mock_installed:
                # Mock not installed initially
                mock_installed.return_value = False
                # Mock successful uv add
                mock_run.return_value = MagicMock(returncode=0)

                result = install_agent(agent_config)
                assert result is True

                # Verify uv add was attempted
                mock_run.assert_called()
                call_args = str(mock_run.call_args)
                assert "uv add requests" in call_args

    def test_agent_check_with_uv_run(self):
        """Test that agent check works with uv run when direct command fails."""
        agent_config = AgentConfig(
            name="test-agent",
            description="Test agent",
            install_commands=["uv add some-package"],
            fallback_install_commands=[],
            check_command="some-command --version",
            launch_command="uv run some-command",
            default_args=[],
            dependencies=["some-package"],
            required_env_vars=[],
            recommended_env_vars=[],
        )

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
        agent_config = AgentConfig(
            name="test-agent",
            description="Test agent",
            install_commands=["uv add some-package"],
            fallback_install_commands=["pip install some-package"],
            check_command="some-command --version",
            launch_command="uv run some-command",
            default_args=[],
            dependencies=["some-package"],
            required_env_vars=[],
            recommended_env_vars=[],
        )

        with patch("subprocess.run") as mock_run:
            with patch("silica.utils.agent_yaml.is_agent_installed") as mock_installed:
                # Mock not installed initially, then installed after fallback
                mock_installed.side_effect = [False, False, True]

                # Mock: uv add fails, pip install succeeds
                mock_run.side_effect = [
                    MagicMock(returncode=1, stderr="uv failed"),  # uv add fails
                    MagicMock(returncode=0),  # pip install succeeds
                ]

                result = install_agent(agent_config)
                assert result is True

                # Verify both commands were tried
                assert mock_run.call_count == 2

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


if __name__ == "__main__":
    pytest.main([__file__])
