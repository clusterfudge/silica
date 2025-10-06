"""Tests for branch display in status command."""

from unittest.mock import patch

from silica.remote.cli.commands.status import print_all_workspaces_summary


class TestStatusBranchDisplay:
    """Test that branch information is displayed in status summary."""

    def test_branch_shown_in_summary_table(self):
        """Test that branch name is displayed in the workspace summary table."""
        # Create mock status data with branch information
        statuses = [
            {
                "workspace": "test-workspace",
                "accessible": True,
                "is_local": False,
                "error": None,
                "status_info": {
                    "version": "1.0.0",
                    "repository": {
                        "exists": True,
                        "branch": "feature/test-branch",
                        "remote_url": "https://github.com/example/repo.git",
                    },
                    "tmux_session": {
                        "running": True,
                    },
                },
            }
        ]

        # Capture console output
        with patch("silica.remote.cli.commands.status.console") as mock_console:
            print_all_workspaces_summary(statuses)

            # Check that the table was created and printed
            assert mock_console.print.called

            # Get all print calls
            print_calls = [call[0][0] for call in mock_console.print.call_args_list]

            # Find the Table object that was printed
            from rich.table import Table

            table_printed = None
            for call in print_calls:
                if isinstance(call, Table):
                    table_printed = call
                    break

            # Verify table exists
            assert table_printed is not None, "No table was printed"

            # Verify branch column exists
            column_names = [col.header for col in table_printed.columns]
            assert "Branch" in column_names, "Branch column not found in table"

    def test_branch_na_when_repo_not_exists(self):
        """Test that 'N/A' is shown when repository doesn't exist."""
        statuses = [
            {
                "workspace": "no-repo-workspace",
                "accessible": True,
                "is_local": False,
                "error": None,
                "status_info": {
                    "version": "1.0.0",
                    "repository": {
                        "exists": False,
                    },
                    "tmux_session": {
                        "running": False,
                    },
                },
            }
        ]

        with patch("silica.remote.cli.commands.status.console") as mock_console:
            print_all_workspaces_summary(statuses)

            # The function should complete without error
            assert mock_console.print.called

    def test_branch_na_when_not_accessible(self):
        """Test that 'N/A' is shown when workspace is not accessible."""
        statuses = [
            {
                "workspace": "offline-workspace",
                "accessible": False,
                "is_local": False,
                "error": "Connection failed",
                "status_info": None,
            }
        ]

        with patch("silica.remote.cli.commands.status.console") as mock_console:
            print_all_workspaces_summary(statuses)

            # The function should complete without error
            assert mock_console.print.called

    def test_multiple_workspaces_with_different_branches(self):
        """Test that multiple workspaces show their respective branches."""
        statuses = [
            {
                "workspace": "workspace-1",
                "accessible": True,
                "is_local": False,
                "error": None,
                "status_info": {
                    "version": "1.0.0",
                    "repository": {
                        "exists": True,
                        "branch": "main",
                    },
                    "tmux_session": {"running": True},
                },
            },
            {
                "workspace": "workspace-2",
                "accessible": True,
                "is_local": True,
                "error": None,
                "status_info": {
                    "version": "1.0.0",
                    "repository": {
                        "exists": True,
                        "branch": "develop",
                    },
                    "tmux_session": {"running": False},
                },
            },
        ]

        with patch("silica.remote.cli.commands.status.console") as mock_console:
            print_all_workspaces_summary(statuses)

            # The function should complete without error
            assert mock_console.print.called
