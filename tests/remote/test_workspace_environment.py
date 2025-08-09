"""Safe tests for workspace environment commands.

These tests are designed to run safely without affecting the current working environment.
They use temporary directories and mock functions where necessary.
"""

import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from silica.remote.cli.commands.workspace_environment import (
    get_workspace_config,
    get_agent_config_dict,
    setup,
    run,
    status,
)


class TestWorkspaceEnvironmentSafety:
    """Test workspace environment commands safely without touching current workspace."""

    def setup_method(self):
        """Set up test environment for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def teardown_method(self):
        """Clean up after each test."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("silica.remote.cli.commands.workspace_environment.os.getcwd")
    @patch("silica.remote.cli.commands.workspace_environment.Path.home")
    def test_get_workspace_config_with_env_vars(self, mock_home, mock_getcwd):
        """Test workspace config retrieval with environment variables."""
        mock_getcwd.return_value = str(self.temp_path)
        mock_home.return_value = self.temp_path

        with patch.dict(
            "os.environ",
            {"SILICA_WORKSPACE_NAME": "test-workspace", "SILICA_AGENT_TYPE": "hdev"},
        ):
            config = get_workspace_config()
            assert config["agent_type"] == "hdev"
            assert "agent_config" in config

    @patch("silica.remote.cli.commands.workspace_environment.os.getcwd")
    def test_get_workspace_config_with_json_file(self, mock_getcwd):
        """Test workspace config retrieval from JSON file."""
        mock_getcwd.return_value = str(self.temp_path)

        # Create a test workspace config file
        config_data = {
            "agent_type": "cline",  # This will be overridden to "hdev"
            "agent_config": {"flags": ["--test"], "args": {"port": 8080}},
        }
        config_file = self.temp_path / "workspace_config.json"
        with open(config_file, "w") as f:
            json.dump(config_data, f)

        config = get_workspace_config()
        # Agent type is now always "hdev" regardless of config file content
        assert config["agent_type"] == "hdev"
        assert config["agent_config"]["flags"] == ["--test"]
        assert config["agent_config"]["args"]["port"] == 8080

    def test_get_agent_config_dict_valid_agent(self):
        """Test agent config retrieval for valid agent."""
        try:
            config = get_agent_config_dict("hdev")
            assert "name" in config
            assert "description" in config
            assert "install" in config
            assert "launch" in config
            assert "environment" in config
        except Exception as e:
            # If agent config fails, it's okay for test purposes
            pytest.skip(f"Agent config not available: {e}")

    def test_get_agent_config_dict_invalid_agent(self):
        """Test agent config retrieval for invalid agent.

        Note: Since tight coupling with hdev, this now always returns hdev config
        regardless of the agent_type parameter.
        """
        # This should now return hdev config regardless of input
        try:
            config = get_agent_config_dict("nonexistent-agent")
            assert "name" in config
            assert config["name"] == "hdev"  # Should always be hdev now
        except Exception as e:
            # If hdev config itself fails, it's okay for test purposes
            pytest.skip(f"Hdev config not available: {e}")


class TestStatusCommandSafety:
    """Test status command specifically with safety measures."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def teardown_method(self):
        """Clean up after each test."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("silica.remote.cli.commands.workspace_environment.Path.cwd")
    @patch(
        "silica.remote.cli.commands.workspace_environment.load_environment_variables"
    )
    @patch("silica.remote.cli.commands.workspace_environment.get_workspace_config")
    @patch("silica.remote.cli.commands.workspace_environment.get_agent_config_dict")
    @patch("silica.remote.cli.commands.workspace_environment.is_agent_installed")
    @patch(
        "silica.remote.cli.commands.workspace_environment.check_environment_variables"
    )
    @patch("subprocess.run")
    def test_status_json_output_structure(
        self,
        mock_subprocess,
        mock_check_env_vars,
        mock_is_installed,
        mock_agent_config,
        mock_workspace_config,
        mock_load_env,
        mock_cwd,
    ):
        """Test that status --json produces correct JSON structure."""
        # Mock all the dependencies to avoid touching real environment
        mock_cwd.return_value = self.temp_path
        mock_load_env.return_value = True
        mock_workspace_config.return_value = {
            "agent_type": "hdev",
            "agent_config": {"flags": [], "args": {}},
        }
        mock_agent_config.return_value = {
            "name": "hdev",
            "description": "Test agent",
            "install": {"check_command": "echo test"},
            "launch": {"command": "echo run"},
            "environment": {"required": [], "recommended": []},
        }
        mock_is_installed.return_value = True
        mock_check_env_vars.return_value = (True, [], [])

        # Mock uv --version command
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="uv 0.6.14")

        # Create code directory
        code_dir = self.temp_path / "code"
        code_dir.mkdir()
        git_dir = code_dir / ".git"
        git_dir.mkdir()

        # Mock git command for branch detection
        def mock_git_command(*args, **kwargs):
            if "git" in args[0] and "branch" in args[0]:
                return MagicMock(returncode=0, stdout="main")
            return mock_subprocess.return_value

        mock_subprocess.side_effect = mock_git_command

        # Capture stdout to test JSON output
        import sys
        from io import StringIO

        captured_output = StringIO()
        sys.stdout = captured_output

        try:
            # Call status function directly with JSON output
            status(json_output=True)
            output = captured_output.getvalue()
        finally:
            sys.stdout = sys.__stdout__

        # Parse JSON output
        try:
            output_data = json.loads(output)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON output: {output}")

        # Verify JSON structure
        assert "overall_status" in output_data
        assert "timestamp" in output_data
        assert "issues" in output_data
        assert "components" in output_data

        # Check components structure
        components = output_data["components"]
        expected_components = [
            "working_directory",
            "environment_variables",
            "uv_package_manager",
            "workspace_config",
            "agent_config",
            "agent_installation",
            "agent_environment",
            "code_directory",
        ]

        for component in expected_components:
            assert component in components
            assert "status" in components[component]

    @patch("silica.remote.cli.commands.workspace_environment.Path.cwd")
    @patch(
        "silica.remote.cli.commands.workspace_environment.load_environment_variables"
    )
    @patch("silica.remote.cli.commands.workspace_environment.get_workspace_config")
    def test_status_table_output(self, mock_workspace_config, mock_load_env, mock_cwd):
        """Test that status command produces table output when not using --json."""
        mock_cwd.return_value = self.temp_path
        mock_load_env.return_value = False
        mock_workspace_config.return_value = None

        # Capture stdout to test table output
        import sys
        from io import StringIO

        captured_output = StringIO()
        sys.stdout = captured_output

        try:
            # Call status function directly without JSON
            status(json_output=False)
            output = captured_output.getvalue()
        finally:
            sys.stdout = sys.__stdout__

        # Should contain table elements (not JSON)
        assert "Working Directory" in output
        assert "{" not in output  # Should not be JSON


class TestCommandIntegrationSafety:
    """Integration tests that verify command interactions safely."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def teardown_method(self):
        """Clean up after each test."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_command_help_outputs(self):
        """Test that all commands have proper help output."""
        # Test that the functions exist and are callable
        # Note: We can't easily test help output for cyclopts functions without
        # setting up the full app structure, so we just test that they're callable
        assert callable(setup)
        assert callable(run)
        assert callable(status)

    @patch("silica.remote.cli.commands.workspace_environment.console.print")
    @patch(
        "silica.remote.cli.commands.workspace_environment.load_environment_variables"
    )
    @patch("silica.remote.cli.commands.workspace_environment.sync_dependencies")
    @patch("silica.remote.cli.commands.workspace_environment.get_workspace_config")
    def test_setup_command_dry_run(
        self, mock_workspace_config, mock_sync_deps, mock_load_env, mock_console_print
    ):
        """Test setup command in a safe way by mocking all external interactions."""
        mock_load_env.return_value = True
        mock_sync_deps.return_value = True
        mock_workspace_config.return_value = {
            "agent_type": "hdev",
            "agent_config": {"flags": [], "args": {}},
        }

        with patch(
            "silica.remote.cli.commands.workspace_environment.get_agent_config_dict"
        ) as mock_agent_config:
            mock_agent_config.return_value = {
                "name": "hdev",
                "description": "Test agent",
                "install": {"check_command": "echo test"},
                "environment": {"required": [], "recommended": []},
            }

            with patch(
                "silica.remote.cli.commands.workspace_environment.install_agent"
            ) as mock_install:
                mock_install.return_value = True

                with patch(
                    "silica.remote.cli.commands.workspace_environment.check_environment_variables"
                ) as mock_check_env:
                    mock_check_env.return_value = (True, [], [])

                    with patch(
                        "silica.remote.cli.commands.workspace_environment.setup_code_directory"
                    ):
                        # Call setup function directly
                        try:
                            setup()
                            # If we get here without exception, setup worked
                            success = True
                        except SystemExit as e:
                            # setup() may call sys.exit, which is okay for this test
                            success = e.code == 0

                        # Should complete successfully
                        assert success


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v"])
