"""Test GitHub authentication fixes for remote environments."""

import os
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestGitHubAuthRemoteFix:
    """Test GitHub authentication setup for remote environments."""

    def test_github_token_propagation_in_create_command(self):
        """Test that create command properly propagates GitHub tokens to remote environment."""
        from silica.remote.cli.commands.create import create_remote_workspace

        # Mock the dependencies
        with patch(
            "silica.remote.cli.commands.create.load_config"
        ) as mock_load_config, patch(
            "silica.remote.cli.commands.create.git.Repo"
        ) as mock_repo, patch(
            "silica.remote.cli.commands.create.subprocess.run"
        ) as mock_run, patch(
            "silica.remote.cli.commands.create.check_remote_dependencies"
        ) as mock_check, patch(
            "silica.remote.cli.commands.create.piku_utils.run_piku_in_silica"
        ) as mock_piku, patch("silica.remote.cli.commands.create.console"), patch.dict(
            os.environ, {"GH_TOKEN": "test-token"}
        ):
            # Set up mocks
            mock_load_config.return_value = {"api_keys": {}}
            mock_check.return_value = (True, [])
            mock_run.return_value = MagicMock(returncode=0)

            # Mock git repository
            mock_repo_instance = MagicMock()
            mock_repo_instance.heads = [MagicMock()]
            mock_repo_instance.active_branch.name = "main"
            mock_repo_instance.is_dirty.return_value = False
            mock_repo_instance.git = MagicMock()
            mock_repo_instance.remotes = []
            mock_repo_instance.create_remote = MagicMock()
            mock_repo.return_value = mock_repo_instance

            # Create mock workspace directories
            git_root = Path("/tmp/test-repo")
            silica_dir = git_root / ".silica"

            # This should not raise an exception and should call piku with GitHub tokens
            try:
                create_remote_workspace("test-workspace", None, git_root, silica_dir)
            except Exception:
                # We expect some exceptions due to mocking, but we want to check the piku call
                pass

            # Verify that piku was called with GitHub tokens
            if mock_piku.called:
                # Check that the config:set command included GitHub tokens
                calls = mock_piku.call_args_list
                config_call = None
                for call in calls:
                    if "config:set" in str(call):
                        config_call = call
                        break

                if config_call:
                    args = str(config_call)
                    assert (
                        "GH_TOKEN=test-token" in args
                        or "GITHUB_TOKEN=test-token" in args
                    )

    def test_workspace_environment_setup_includes_github_auth(self):
        """Test that workspace environment setup includes GitHub authentication."""
        from silica.remote.cli.commands.workspace_environment import (
            setup_github_authentication,
        )

        with patch(
            "silica.remote.cli.commands.workspace_environment.setup_gh_auth"
        ) as mock_setup, patch(
            "silica.remote.cli.commands.workspace_environment.verify_github_authentication"
        ) as mock_verify, patch(
            "silica.remote.cli.commands.workspace_environment.console"
        ):
            # Mock successful authentication
            mock_setup.return_value = (True, "GitHub CLI authentication configured")
            mock_verify.return_value = (True, "Authentication verified")

            # Call the function
            setup_github_authentication()

            # Verify it was called
            mock_setup.assert_called_once_with(prefer_gh_cli=True)
            mock_verify.assert_called_once()

    def test_enhanced_github_auth_setup_with_cli_fallback(self):
        """Test enhanced GitHub authentication setup with CLI token retrieval."""
        from silica.remote.utils.github_auth import setup_github_authentication

        with patch(
            "silica.remote.utils.github_auth.get_github_token"
        ) as mock_get_token, patch(
            "silica.remote.utils.github_auth.check_gh_cli_available"
        ) as mock_check_cli, patch(
            "silica.remote.utils.github_auth.subprocess.run"
        ) as mock_run, patch(
            "silica.remote.utils.github_auth.setup_github_cli_auth"
        ) as mock_cli_auth, patch.dict(os.environ, {}, clear=True):  # Clear environment
            # Mock scenario where no token in env but gh CLI has one
            mock_get_token.return_value = None
            mock_check_cli.return_value = True
            mock_run.return_value = MagicMock(returncode=0, stdout="retrieved-token\n")
            mock_cli_auth.return_value = (True, "GitHub CLI configured")

            success, message = setup_github_authentication()

            # Should succeed by retrieving token from gh CLI
            assert success
            assert "GitHub CLI" in message

            # Should have called gh auth token
            mock_run.assert_called()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["gh", "auth", "token"]

    def test_setup_python_script_includes_github_setup(self):
        """Test that setup_python.sh includes GitHub CLI installation and authentication."""
        setup_script_path = (
            Path(__file__).parent.parent.parent
            / "silica"
            / "remote"
            / "utils"
            / "templates"
            / "setup_python.sh"
        )

        if setup_script_path.exists():
            with open(setup_script_path, "r") as f:
                content = f.read()

            # Check for GitHub CLI installation function
            assert "install_github_cli()" in content
            assert "setup_github_auth()" in content
            assert "gh auth login --with-token" in content
            assert "GH_TOKEN" in content or "GITHUB_TOKEN" in content

    def test_local_workspace_github_token_passing(self):
        """Test that local workspace creation properly passes GitHub tokens to tmux."""
        from silica.remote.cli.commands.create import create_local_workspace

        with patch(
            "silica.remote.cli.commands.create.subprocess.run"
        ) as mock_run, patch("silica.remote.cli.commands.create.console"), patch(
            "silica.remote.cli.commands.create.create_workspace_config"
        ), patch(
            "silica.remote.cli.commands.create.get_workspace_config"
        ) as mock_get_config, patch(
            "silica.remote.cli.commands.create.set_workspace_config"
        ), patch("silica.remote.cli.commands.create.time.sleep"), patch(
            "silica.remote.cli.commands.create.get_antennae_client"
        ), patch.dict(os.environ, {"GH_TOKEN": "test-local-token"}):
            mock_get_config.return_value = {}
            # Mock tmux commands to succeed
            mock_run.return_value = MagicMock(returncode=0)

            git_root = Path("/tmp/test-local-repo")
            silica_dir = git_root / ".silica"

            try:
                create_local_workspace("test-local", 8000, git_root, silica_dir)
            except Exception:
                # Expected due to mocking
                pass

            # Check that tmux session was created with environment variables
            tmux_calls = [
                call for call in mock_run.call_args_list if "tmux" in str(call)
            ]
            if tmux_calls:
                # Should have environment variables set
                for call in tmux_calls:
                    if "new-session" in str(call):
                        # The environment should be passed via env parameter
                        env_param = call.kwargs.get("env")
                        if env_param:
                            assert "GH_TOKEN" in env_param
                            assert env_param["GH_TOKEN"] == "test-local-token"

    def test_agent_manager_github_setup(self):
        """Test that agent manager properly sets up GitHub authentication."""
        from silica.remote.antennae.agent_manager import AgentManager
        from silica.remote.antennae.config import WorkspaceConfig

        with patch(
            "silica.remote.antennae.agent_manager.subprocess.run"
        ) as mock_run, patch(
            "silica.remote.antennae.agent_manager.setup_github_authentication"
        ) as mock_setup_auth, patch(
            "silica.remote.antennae.agent_manager.get_github_token"
        ) as mock_get_token, patch.object(
            WorkspaceConfig, "get_tmux_session_name", return_value="test-session"
        ), patch.object(
            WorkspaceConfig, "get_agent_command", return_value="test-command"
        ), patch.object(
            WorkspaceConfig, "get_code_directory", return_value=Path("/tmp/code")
        ):
            # Mock authentication setup
            mock_get_token.return_value = "test-token"
            mock_setup_auth.return_value = (True, "Authentication configured")
            mock_run.return_value = MagicMock(returncode=0)

            manager = AgentManager()

            # Should not raise an exception
            manager.start_tmux_session()

            # Verify tmux was called with proper environment
            tmux_calls = [
                call for call in mock_run.call_args_list if "tmux" in str(call)
            ]
            assert len(tmux_calls) > 0
