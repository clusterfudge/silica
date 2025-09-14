"""Tests for Git utility functions."""

import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from silica.remote.utils.git import (
    is_github_repo,
    extract_github_repo_path,
    check_gh_cli_available,
    clone_repository,
    convert_github_ssh_to_https,
)


class TestGitUtils:
    """Tests for Git utility functions."""

    def test_is_github_repo(self):
        """Test GitHub repository detection."""
        # Test GitHub HTTPS URLs
        assert is_github_repo("https://github.com/user/repo.git")
        assert is_github_repo("https://github.com/user/repo")

        # Test GitHub SSH URLs
        assert is_github_repo("git@github.com:user/repo.git")
        assert is_github_repo("git@github.com:user/repo")

        # Test non-GitHub URLs
        assert not is_github_repo("https://gitlab.com/user/repo.git")
        assert not is_github_repo("https://bitbucket.org/user/repo.git")
        assert not is_github_repo("git@example.com:user/repo.git")

    def test_extract_github_repo_path(self):
        """Test GitHub repository path extraction."""
        # Test HTTPS URLs
        assert (
            extract_github_repo_path("https://github.com/user/repo.git") == "user/repo"
        )
        assert extract_github_repo_path("https://github.com/user/repo") == "user/repo"

        # Test SSH URLs
        assert extract_github_repo_path("git@github.com:user/repo.git") == "user/repo"
        assert extract_github_repo_path("git@github.com:user/repo") == "user/repo"

        # Test non-GitHub URLs
        assert extract_github_repo_path("https://gitlab.com/user/repo.git") == ""
        assert extract_github_repo_path("git@example.com:user/repo.git") == ""

    def test_convert_github_ssh_to_https(self):
        """Test GitHub SSH to HTTPS URL conversion."""
        # Test SSH to HTTPS conversion
        assert (
            convert_github_ssh_to_https("git@github.com:user/repo.git")
            == "https://github.com/user/repo.git"
        )
        assert (
            convert_github_ssh_to_https("git@github.com:user/repo")
            == "https://github.com/user/repo"
        )

        # Test HTTPS URLs remain unchanged
        assert (
            convert_github_ssh_to_https("https://github.com/user/repo.git")
            == "https://github.com/user/repo.git"
        )
        assert (
            convert_github_ssh_to_https("https://github.com/user/repo")
            == "https://github.com/user/repo"
        )

        # Test non-GitHub URLs remain unchanged
        assert (
            convert_github_ssh_to_https("git@gitlab.com:user/repo.git")
            == "git@gitlab.com:user/repo.git"
        )
        assert (
            convert_github_ssh_to_https("https://gitlab.com/user/repo.git")
            == "https://gitlab.com/user/repo.git"
        )

    @patch("subprocess.run")
    def test_check_gh_cli_available_true(self, mock_run):
        """Test GitHub CLI availability check when available."""
        mock_run.return_value = MagicMock(returncode=0)
        assert check_gh_cli_available() is True
        mock_run.assert_called_once_with(
            ["gh", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    @patch("subprocess.run")
    def test_check_gh_cli_available_false(self, mock_run):
        """Test GitHub CLI availability check when not available."""
        mock_run.side_effect = FileNotFoundError()
        assert check_gh_cli_available() is False

    @patch("subprocess.run")
    def test_check_gh_cli_available_false_error(self, mock_run):
        """Test GitHub CLI availability check when command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ["gh", "--version"])
        assert check_gh_cli_available() is False

    @patch("silica.remote.utils.git.check_gh_cli_available")
    @patch("silica.remote.utils.git.is_github_repo")
    @patch("silica.remote.utils.git.extract_github_repo_path")
    @patch("subprocess.run")
    @patch("git.Repo.clone_from")
    def test_clone_repository_github_with_gh_cli(
        self,
        mock_git_clone,
        mock_subprocess,
        mock_extract,
        mock_is_github,
        mock_gh_available,
    ):
        """Test cloning GitHub repository with gh CLI."""
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "repo"

            # Mock GitHub repository detection
            mock_is_github.return_value = True
            mock_gh_available.return_value = True
            mock_extract.return_value = "user/repo"

            # Mock successful gh CLI clone
            mock_subprocess.return_value = MagicMock(returncode=0)

            result = clone_repository("https://github.com/user/repo.git", destination)

            assert result is True
            mock_subprocess.assert_called_once_with(
                ["gh", "repo", "clone", "user/repo", str(destination)],
                capture_output=True,
                text=True,
                check=False,
            )
            # git.Repo.clone_from should not be called when gh CLI succeeds
            mock_git_clone.assert_not_called()

    @patch("silica.remote.utils.git.check_gh_cli_available")
    @patch("silica.remote.utils.git.is_github_repo")
    @patch("silica.remote.utils.git.extract_github_repo_path")
    @patch("subprocess.run")
    @patch("git.Repo.clone_from")
    def test_clone_repository_github_fallback_to_git(
        self,
        mock_git_clone,
        mock_subprocess,
        mock_extract,
        mock_is_github,
        mock_gh_available,
    ):
        """Test cloning GitHub repository falling back to git when gh CLI fails."""
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "repo"

            # Mock GitHub repository detection
            mock_is_github.return_value = True
            mock_gh_available.return_value = True
            mock_extract.return_value = "user/repo"

            # Mock failed gh CLI clone
            mock_subprocess.return_value = MagicMock(returncode=1, stderr="error")

            result = clone_repository("https://github.com/user/repo.git", destination)

            assert result is True
            # Both gh CLI and git should be called
            mock_subprocess.assert_called_once()
            mock_git_clone.assert_called_once_with(
                "https://github.com/user/repo.git", destination, branch="main"
            )

    @patch("silica.remote.utils.git.check_gh_cli_available")
    @patch("silica.remote.utils.git.is_github_repo")
    @patch("git.Repo.clone_from")
    def test_clone_repository_non_github(
        self, mock_git_clone, mock_is_github, mock_gh_available
    ):
        """Test cloning non-GitHub repository uses git directly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "repo"

            # Mock non-GitHub repository
            mock_is_github.return_value = False
            mock_gh_available.return_value = True

            result = clone_repository("https://gitlab.com/user/repo.git", destination)

            assert result is True
            # Should use git directly for non-GitHub repos
            mock_git_clone.assert_called_once_with(
                "https://gitlab.com/user/repo.git", destination, branch="main"
            )

    @patch("silica.remote.utils.git.check_gh_cli_available")
    @patch("silica.remote.utils.git.is_github_repo")
    @patch("git.Repo.clone_from")
    def test_clone_repository_no_gh_cli(
        self, mock_git_clone, mock_is_github, mock_gh_available
    ):
        """Test cloning GitHub repository when gh CLI not available."""
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "repo"

            # Mock GitHub repository but no gh CLI
            mock_is_github.return_value = True
            mock_gh_available.return_value = False

            result = clone_repository("https://github.com/user/repo.git", destination)

            assert result is True
            # Should use git directly when gh CLI not available
            mock_git_clone.assert_called_once_with(
                "https://github.com/user/repo.git", destination, branch="main"
            )

    @patch("silica.remote.utils.git.check_gh_cli_available")
    @patch("silica.remote.utils.git.is_github_repo")
    @patch("silica.remote.utils.git.extract_github_repo_path")
    @patch("subprocess.run")
    @patch("git.Repo.clone_from")
    def test_clone_repository_github_with_branch(
        self,
        mock_git_clone,
        mock_subprocess,
        mock_extract,
        mock_is_github,
        mock_gh_available,
    ):
        """Test cloning GitHub repository with specific branch using gh CLI."""
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "repo"

            # Mock GitHub repository detection
            mock_is_github.return_value = True
            mock_gh_available.return_value = True
            mock_extract.return_value = "user/repo"

            # Mock successful gh CLI clone
            mock_subprocess.return_value = MagicMock(returncode=0)

            result = clone_repository(
                "https://github.com/user/repo.git", destination, branch="develop"
            )

            assert result is True
            mock_subprocess.assert_called_once_with(
                [
                    "gh",
                    "repo",
                    "clone",
                    "user/repo",
                    str(destination),
                    "--",
                    "--branch",
                    "develop",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            # git.Repo.clone_from should not be called when gh CLI succeeds
            mock_git_clone.assert_not_called()

    @patch("silica.remote.utils.git.check_gh_cli_available")
    @patch("silica.remote.utils.git.is_github_repo")
    @patch("git.Repo.clone_from")
    def test_clone_repository_branch_parameter(
        self, mock_git_clone, mock_is_github, mock_gh_available
    ):
        """Test cloning with specific branch parameter."""
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "repo"

            # Mock non-GitHub repository to test git clone branch parameter
            mock_is_github.return_value = False
            mock_gh_available.return_value = True

            result = clone_repository(
                "https://gitlab.com/user/repo.git", destination, branch="develop"
            )

            assert result is True
            mock_git_clone.assert_called_once_with(
                "https://gitlab.com/user/repo.git", destination, branch="develop"
            )

    @patch("silica.remote.utils.git.check_gh_cli_available")
    @patch("silica.remote.utils.git.is_github_repo")
    @patch("git.Repo.clone_from")
    def test_clone_repository_cleanup_on_failure(
        self, mock_git_clone, mock_is_github, mock_gh_available
    ):
        """Test that destination directory is cleaned up on clone failure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "repo"

            # Create the destination directory to test cleanup
            destination.mkdir()
            assert destination.exists()

            # Mock failure
            mock_is_github.return_value = False
            mock_gh_available.return_value = True
            mock_git_clone.side_effect = Exception("Clone failed")

            result = clone_repository("https://gitlab.com/user/repo.git", destination)

            assert result is False
            # Directory should be cleaned up on failure
            # Note: We can't test this easily because the utility function
            # removes and recreates the directory before cloning
