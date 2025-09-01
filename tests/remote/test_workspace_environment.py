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
    get_required_env_vars,
    verify_silica_available,
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
            {
                "SILICA_WORKSPACE_NAME": "test-workspace",
            },
        ):
            config = get_workspace_config()
            assert "agent_config" in config
            # No agent_type field anymore - only one agent

    @patch("silica.remote.cli.commands.workspace_environment.os.getcwd")
    def test_get_workspace_config_with_json_file(self, mock_getcwd):
        """Test workspace config retrieval from JSON file."""
        mock_getcwd.return_value = str(self.temp_path)

        # Create a test workspace config file
        config_data = {
            "agent_config": {"flags": ["--test"], "args": {"port": 8080}},
        }
        config_file = self.temp_path / "workspace_config.json"
        with open(config_file, "w") as f:
            json.dump(config_data, f)

        config = get_workspace_config()
        # Config should be loaded from file
        assert config["agent_config"]["flags"] == ["--test"]
        assert config["agent_config"]["args"]["port"] == 8080

    def test_get_required_env_vars(self):
        """Test getting required environment variables."""
        env_vars = get_required_env_vars()
        assert isinstance(env_vars, list)
        assert len(env_vars) > 0

        # Check that required vars have name and description
        for env_var in env_vars:
            assert "name" in env_var
            assert "description" in env_var

        # Check that expected vars are present
        var_names = [var["name"] for var in env_vars]
        assert "ANTHROPIC_API_KEY" in var_names
        assert "GH_TOKEN" in var_names

    def test_verify_silica_available(self):
        """Test silica availability check."""
        from unittest.mock import MagicMock

        with patch("subprocess.run") as mock_run:
            # Test successful case
            mock_run.return_value = MagicMock(returncode=0)
            result = verify_silica_available()
            assert result is True

            # Test failed case
            mock_run.return_value = MagicMock(returncode=1)
            result = verify_silica_available()
            assert result is False


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
    @patch("silica.remote.cli.commands.workspace_environment.verify_silica_available")
    @patch("silica.remote.cli.commands.workspace_environment.get_required_env_vars")
    @patch("subprocess.run")
    def test_status_json_output_structure(
        self,
        mock_subprocess,
        mock_env_vars,
        mock_silica_available,
        mock_workspace_config,
        mock_load_env,
        mock_cwd,
    ):
        """Test that status --json produces correct JSON structure."""
        # Mock all the dependencies to avoid touching real environment
        mock_cwd.return_value = self.temp_path
        mock_load_env.return_value = True
        mock_workspace_config.return_value = {
            "agent_config": {"flags": [], "args": {}},
        }
        mock_silica_available.return_value = True
        mock_env_vars.return_value = [
            {"name": "ANTHROPIC_API_KEY", "description": "API key"},
            {"name": "GH_TOKEN", "description": "GitHub token"},
        ]

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
            "agent_config": {"flags": [], "args": {}},
        }

        with patch(
            "silica.remote.cli.commands.workspace_environment.verify_silica_available"
        ) as mock_silica_available:
            mock_silica_available.return_value = True
            with patch(
                "silica.remote.cli.commands.workspace_environment.setup_code_directory"
            ):
                with patch("os.getenv") as mock_getenv:
                    # Mock environment variables to be set
                    def mock_env(key):
                        env_vars = {
                            "ANTHROPIC_API_KEY": "test-key",
                            "GH_TOKEN": "test-token",
                            "BRAVE_SEARCH_API_KEY": "test-search-key",
                        }
                        return env_vars.get(key)

                    mock_getenv.side_effect = mock_env

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

    def test_verify_silica_available(self):
        """Test silica availability check."""
        with patch("subprocess.run") as mock_run:
            # Test successful case
            mock_run.return_value = MagicMock(returncode=0)
            result = verify_silica_available()
            assert result is True

            # Test failed case
            mock_run.return_value = MagicMock(returncode=1)
            result = verify_silica_available()
            assert result is False
