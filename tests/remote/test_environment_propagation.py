"""Test environment variable propagation to subprocesses."""

import os
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch

# agent_runner module removed - load_environment_variables only in workspace_environment now
from silica.remote.cli.commands.workspace_environment import (
    load_environment_variables as we_load_environment_variables,
)


class TestEnvironmentPropagation:
    """Test that environment variables are properly loaded and passed to subprocesses."""

    def test_workspace_environment_loads_env_and_live_env_as_agent_runner(self):
        """Test that workspace environment loads both ENV and LIVE_ENV files (replaces agent_runner test)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock the environment file paths
            env_content = "TEST_VAR1=value1\nTEST_VAR2=value2\n"
            live_env_content = "TEST_VAR2=overridden_value\nTEST_VAR3=value3\n"

            piku_envs_dir = Path(temp_dir) / ".piku" / "envs" / "test-app"
            piku_envs_dir.mkdir(parents=True, exist_ok=True)

            env_file = piku_envs_dir / "ENV"
            live_env_file = piku_envs_dir / "LIVE_ENV"

            env_file.write_text(env_content)
            live_env_file.write_text(live_env_content)

            # Mock Path.home() and Path.cwd()
            with patch(
                "silica.remote.cli.commands.workspace_environment.Path.home",
                return_value=Path(temp_dir),
            ), patch(
                "silica.remote.cli.commands.workspace_environment.Path.cwd",
                return_value=Path(temp_dir) / "test-app",
            ):
                # Clear environment variables first
                original_env = {}
                for var in ["TEST_VAR1", "TEST_VAR2", "TEST_VAR3"]:
                    original_env[var] = os.environ.pop(var, None)

                try:
                    we_load_environment_variables(silent=True)

                    # Verify environment variables are loaded
                    assert os.environ.get("TEST_VAR1") == "value1"
                    assert (
                        os.environ.get("TEST_VAR2") == "overridden_value"
                    )  # LIVE_ENV takes precedence
                    assert os.environ.get("TEST_VAR3") == "value3"

                finally:
                    # Restore original environment
                    for var, value in original_env.items():
                        if value is not None:
                            os.environ[var] = value
                        else:
                            os.environ.pop(var, None)

    def test_workspace_environment_loads_env_and_live_env(self):
        """Test that workspace environment loads both ENV and LIVE_ENV files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock the environment file paths
            env_content = "WE_TEST_VAR1=value1\nWE_TEST_VAR2=value2\n"
            live_env_content = "WE_TEST_VAR2=overridden_value\nWE_TEST_VAR3=value3\n"

            piku_envs_dir = Path(temp_dir) / ".piku" / "envs" / "test-app"
            piku_envs_dir.mkdir(parents=True, exist_ok=True)

            env_file = piku_envs_dir / "ENV"
            live_env_file = piku_envs_dir / "LIVE_ENV"

            env_file.write_text(env_content)
            live_env_file.write_text(live_env_content)

            # Mock Path.home() and Path.cwd()
            with patch(
                "silica.remote.cli.commands.workspace_environment.Path.home",
                return_value=Path(temp_dir),
            ), patch(
                "silica.remote.cli.commands.workspace_environment.Path.cwd",
                return_value=Path(temp_dir) / "test-app",
            ):
                # Clear environment variables first
                original_env = {}
                for var in ["WE_TEST_VAR1", "WE_TEST_VAR2", "WE_TEST_VAR3"]:
                    original_env[var] = os.environ.pop(var, None)

                try:
                    result = we_load_environment_variables(silent=True)

                    # Verify environment variables are loaded
                    assert result is True
                    assert os.environ.get("WE_TEST_VAR1") == "value1"
                    assert (
                        os.environ.get("WE_TEST_VAR2") == "overridden_value"
                    )  # LIVE_ENV takes precedence
                    assert os.environ.get("WE_TEST_VAR3") == "value3"

                finally:
                    # Restore original environment
                    for var, value in original_env.items():
                        if value is not None:
                            os.environ[var] = value
                        else:
                            os.environ.pop(var, None)

    def test_environment_variables_with_quotes(self):
        """Test that environment variables with quotes are handled correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock the environment file with quoted values
            env_content = "QUOTED_VAR1=\"value with spaces\"\nQUOTED_VAR2='single quoted'\nNO_QUOTES=simple\n"

            piku_envs_dir = Path(temp_dir) / ".piku" / "envs" / "test-app"
            piku_envs_dir.mkdir(parents=True, exist_ok=True)

            env_file = piku_envs_dir / "ENV"
            env_file.write_text(env_content)

            # Mock Path.home() and Path.cwd()
            with patch(
                "silica.remote.cli.commands.workspace_environment.Path.home",
                return_value=Path(temp_dir),
            ), patch(
                "silica.remote.cli.commands.workspace_environment.Path.cwd",
                return_value=Path(temp_dir) / "test-app",
            ):
                # Clear environment variables first
                original_env = {}
                for var in ["QUOTED_VAR1", "QUOTED_VAR2", "NO_QUOTES"]:
                    original_env[var] = os.environ.pop(var, None)

                try:
                    we_load_environment_variables(silent=True)

                    # Verify environment variables are loaded with quotes stripped
                    assert os.environ.get("QUOTED_VAR1") == "value with spaces"
                    assert os.environ.get("QUOTED_VAR2") == "single quoted"
                    assert os.environ.get("NO_QUOTES") == "simple"

                finally:
                    # Restore original environment
                    for var, value in original_env.items():
                        if value is not None:
                            os.environ[var] = value
                        else:
                            os.environ.pop(var, None)

    def test_environment_propagation_to_subprocess(self):
        """Test that environment variables are properly passed to subprocess calls."""
        # Set a test environment variable
        test_var_name = "SILICA_TEST_ENV_VAR"
        test_var_value = "test_value_12345"

        original_value = os.environ.get(test_var_name)
        os.environ[test_var_name] = test_var_value

        try:
            # Test that subprocess.run with env=os.environ.copy() can see our variable
            result = subprocess.run(
                [
                    "python",
                    "-c",
                    f"import os; print(os.environ.get('{test_var_name}', 'NOT_FOUND'))",
                ],
                capture_output=True,
                text=True,
                env=os.environ.copy(),
            )

            assert result.returncode == 0
            assert result.stdout.strip() == test_var_value

        finally:
            # Restore original environment
            if original_value is not None:
                os.environ[test_var_name] = original_value
            else:
                os.environ.pop(test_var_name, None)

    def test_gh_token_environment_variable(self):
        """Test that GH_TOKEN is properly loaded and available to subprocesses."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock environment file with GH_TOKEN
            env_content = "GH_TOKEN=test_gh_token_value\nOTHER_VAR=other_value\n"

            piku_envs_dir = Path(temp_dir) / ".piku" / "envs" / "test-app"
            piku_envs_dir.mkdir(parents=True, exist_ok=True)

            env_file = piku_envs_dir / "ENV"
            env_file.write_text(env_content)

            # Mock Path.home() and Path.cwd()
            with patch(
                "silica.remote.cli.commands.workspace_environment.Path.home",
                return_value=Path(temp_dir),
            ), patch(
                "silica.remote.cli.commands.workspace_environment.Path.cwd",
                return_value=Path(temp_dir) / "test-app",
            ):
                # Clear GH_TOKEN environment variable first
                original_gh_token = os.environ.pop("GH_TOKEN", None)

                try:
                    we_load_environment_variables(silent=True)

                    # Verify GH_TOKEN is loaded
                    assert os.environ.get("GH_TOKEN") == "test_gh_token_value"

                    # Test that it's available to subprocess (simulating gh command)
                    result = subprocess.run(
                        [
                            "python",
                            "-c",
                            "import os; print(os.environ.get('GH_TOKEN', 'NOT_FOUND'))",
                        ],
                        capture_output=True,
                        text=True,
                        env=os.environ.copy(),
                    )

                    assert result.returncode == 0
                    assert result.stdout.strip() == "test_gh_token_value"

                finally:
                    # Restore original environment
                    if original_gh_token is not None:
                        os.environ["GH_TOKEN"] = original_gh_token
                    else:
                        os.environ.pop("GH_TOKEN", None)
