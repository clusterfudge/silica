"""Test tmux session naming with workspace and project name.

This test validates the correct approach for tmux session naming:
- WORKSPACE_NAME: logical workspace name (e.g., "agent")
- PROJECT_NAME: project name from git repo (e.g., "list-of-lists")
- Tmux session: "${WORKSPACE_NAME}-${PROJECT_NAME}" (e.g., "agent-list-of-lists")

This should match the piku app name exactly.
"""

import os
import pytest
from unittest.mock import patch

from silica.remote.antennae.config import AntennaeConfig


class TestTmuxSessionNamingWithProject:
    """Test tmux session naming using workspace + project name."""

    def test_tmux_session_name_from_workspace_and_project(self):
        """Test that tmux session name is constructed from WORKSPACE_NAME + PROJECT_NAME."""
        with patch.dict(
            os.environ, {"WORKSPACE_NAME": "agent", "PROJECT_NAME": "list-of-lists"}
        ):
            config = AntennaeConfig()

            # Tmux session should be workspace-project
            assert config.get_tmux_session_name() == "agent-list-of-lists"

            # Workspace name should still be just the workspace
            assert config.get_workspace_name() == "agent"

            # Project name should be accessible
            assert config.get_project_name() == "list-of-lists"

    def test_tmux_session_name_different_combinations(self):
        """Test different workspace + project combinations."""
        test_cases = [
            # (workspace, project) -> expected_session_name
            ("agent", "list-of-lists", "agent-list-of-lists"),
            ("test-workspace", "my-project", "test-workspace-my-project"),
            ("dev", "silica", "dev-silica"),
            ("production", "api-server", "production-api-server"),
        ]

        for workspace, project, expected_session in test_cases:
            with patch.dict(
                os.environ, {"WORKSPACE_NAME": workspace, "PROJECT_NAME": project}
            ):
                config = AntennaeConfig()

                assert config.get_tmux_session_name() == expected_session
                assert config.get_workspace_name() == workspace
                assert config.get_project_name() == project

    def test_project_name_required(self):
        """Test that PROJECT_NAME is required when WORKSPACE_NAME is set."""
        with patch.dict(os.environ, {"WORKSPACE_NAME": "agent"}, clear=True):
            config = AntennaeConfig()

            # Should fail if PROJECT_NAME is not set
            with pytest.raises(
                RuntimeError, match="PROJECT_NAME environment variable must be set"
            ):
                config.get_tmux_session_name()

    def test_workspace_name_required(self):
        """Test that WORKSPACE_NAME is required."""
        with patch.dict(os.environ, {"PROJECT_NAME": "list-of-lists"}, clear=True):
            config = AntennaeConfig()

            # Should fail if WORKSPACE_NAME is not set
            with pytest.raises(
                RuntimeError, match="WORKSPACE_NAME environment variable must be set"
            ):
                config.get_workspace_name()

    def test_piku_app_name_matches_tmux_session(self):
        """Test that the constructed tmux session name matches expected piku app name."""
        workspace_name = "agent"
        project_name = "list-of-lists"
        expected_piku_app_name = f"{workspace_name}-{project_name}"

        with patch.dict(
            os.environ, {"WORKSPACE_NAME": workspace_name, "PROJECT_NAME": project_name}
        ):
            config = AntennaeConfig()

            # Tmux session should match the piku app name pattern
            assert config.get_tmux_session_name() == expected_piku_app_name
            assert config.get_tmux_session_name() == "agent-list-of-lists"

    def test_original_problem_is_solved(self):
        """Test that the original 'agent-agent' problem is solved."""
        # The original problem: WORKSPACE_NAME=agent created session "agent-agent"
        # The solution: WORKSPACE_NAME=agent + PROJECT_NAME=list-of-lists creates "agent-list-of-lists"

        with patch.dict(
            os.environ, {"WORKSPACE_NAME": "agent", "PROJECT_NAME": "list-of-lists"}
        ):
            config = AntennaeConfig()
            session_name = config.get_tmux_session_name()

            # Should NOT be the problematic "agent-agent"
            assert session_name != "agent-agent"

            # Should be the correct "agent-list-of-lists"
            assert session_name == "agent-list-of-lists"
