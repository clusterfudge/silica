#!/usr/bin/env python3
"""Tests for UV-based agent management with built-in silica developer."""

import pytest
import tempfile
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add silica to path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

# Test the simplified functions
from silica.remote.cli.commands.workspace_environment import (
    verify_silica_available,
    get_silica_developer_command,
)


class TestSilicaDeveloperManagement:
    """Test built-in silica developer management."""

    def test_silica_availability_check(self):
        """Test that silica availability check works correctly."""
        # Test with mocked subprocess to avoid actual execution
        with patch("subprocess.run") as mock_run:
            # Mock successful silica command
            mock_run.return_value = MagicMock(returncode=0)

            result = verify_silica_available()
            assert result is True

            # Verify silica --help was called
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]  # Get the command arguments
            assert call_args == ["silica", "--help"]

    def test_silica_availability_check_failure(self):
        """Test silica availability check when command fails."""
        with patch("subprocess.run") as mock_run:
            # Mock failed silica command
            mock_run.return_value = MagicMock(returncode=1)

            result = verify_silica_available()
            assert result is False

    def test_silica_availability_check_not_found(self):
        """Test silica availability check when command is not found."""
        with patch("subprocess.run") as mock_run:
            # Mock FileNotFoundError (command not found)
            mock_run.side_effect = FileNotFoundError()

            result = verify_silica_available()
            assert result is False

    def test_silica_developer_command_generation(self):
        """Test generation of silica developer command."""
        workspace_config = {"agent_config": {"flags": [], "args": {}}}

        command = get_silica_developer_command(workspace_config)

        expected_parts = [
            "uv",
            "run",
            "silica",
            "developer",
            "--dwr",
            "--persona",
            "autonomous_engineer",
        ]
        assert command == " ".join(expected_parts)

    def test_silica_developer_command_with_custom_flags(self):
        """Test generation of silica developer command with custom flags."""
        workspace_config = {
            "agent_config": {
                "flags": ["--verbose"],
                "args": {"timeout": 60, "debug": True},
            }
        }

        command = get_silica_developer_command(workspace_config)

        # Should contain base command + custom flags and args
        assert "uv run silica developer --dwr --persona autonomous_engineer" in command
        assert "--verbose" in command
        assert "--timeout 60" in command
        assert "--debug" in command

    def test_workspace_directory_structure(self):
        """Test that workspace directory structure can be set up correctly."""
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

    def test_command_generation_workflow(self):
        """Test the basic command generation workflow."""
        # Simple workspace config
        workspace_config = {"agent_config": {"flags": [], "args": {}}}

        # Test command generation
        result = get_silica_developer_command(workspace_config)

        # Should return the hardcoded silica developer command
        assert "uv run silica developer" in result
        assert "--dwr" in result
        assert "autonomous_engineer" in result


if __name__ == "__main__":
    pytest.main([__file__])
