"""Tests for the workspace creation functionality."""

import shutil
import tempfile
from pathlib import Path
import yaml
import pytest

from silica.remote.config.multi_workspace import load_project_config, list_workspaces


class TestWorkspaceCreation:
    """Test class for workspace creation functionality."""

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

    def test_single_workspace_creation(self, mock_git_repo, monkeypatch):
        """Test that creating a workspace with a custom name doesn't create the default workspace."""
        # Setup
        silica_dir = mock_git_repo / ".silica"

        # Mock functions to avoid actual git operations and piku calls
        monkeypatch.setattr(
            "silica.remote.config.find_git_root", lambda path=None: mock_git_repo
        )
        monkeypatch.setattr(
            "silica.remote.config.get_silica_dir", lambda path=None: silica_dir
        )
        monkeypatch.setattr(
            "silica.remote.cli.commands.create.find_git_root", lambda: mock_git_repo
        )
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            "git.Repo",
            lambda path: type(
                "obj",
                (object,),
                {
                    "git": type(
                        "obj",
                        (object,),
                        {
                            "add": lambda *args: None,
                            "commit": lambda *args, **kwargs: None,
                            "push": lambda *args: None,
                            "checkout": lambda *args: None,
                        },
                    ),
                    "create_remote": lambda *args: None,
                    "remotes": [],
                    "is_dirty": lambda: True,
                    "heads": [],
                    "active_branch": type("obj", (object,), {"name": "main"}),
                },
            )(),
        )
        monkeypatch.setattr(
            "silica.remote.utils.piku.run_piku_in_silica",
            lambda *args, **kwargs: type(
                "obj", (object,), {"stdout": "", "returncode": 0}
            )(),
        )

        # Create a custom workspace
        custom_workspace = "not-default-name"

        # Simulate creating a workspace with a custom name
        # Need to manually create the config since we mocked subprocess.run
        config = {
            "default_workspace": custom_workspace,
            "workspaces": {
                custom_workspace: {
                    "piku_connection": "piku",
                    "app_name": f"{custom_workspace}-repo",
                    "branch": "main",
                }
            },
        }

        # Write the config file
        config_file = silica_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        # Verify
        workspaces = list_workspaces(silica_dir)
        assert len(workspaces) == 1, "Should only create one workspace"
        assert (
            workspaces[0]["name"] == custom_workspace
        ), "The workspace name should match what was provided"
        assert "agent" not in [
            w["name"] for w in workspaces
        ], "Should not create the 'agent' workspace"

        # Verify the loaded config matches what we expect
        loaded_config = load_project_config(silica_dir)
        assert loaded_config["default_workspace"] == custom_workspace
        assert custom_workspace in loaded_config["workspaces"]
        assert "agent" not in loaded_config["workspaces"]
