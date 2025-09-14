"""Tests for GitHub authentication utilities."""

import os
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock


from silica.remote.utils.github_auth import (
    get_github_token,
    check_gh_cli_available,
    setup_git_credentials_for_github,
    setup_github_cli_auth,
    setup_github_authentication,
    verify_github_authentication,
)


class TestGitHubAuth:
    """Tests for GitHub authentication utilities."""

    def test_get_github_token_gh_token(self):
        """Test getting GitHub token from GH_TOKEN."""
        with patch.dict(os.environ, {"GH_TOKEN": "test_gh_token"}, clear=True):
            assert get_github_token() == "test_gh_token"

    def test_get_github_token_github_token(self):
        """Test getting GitHub token from GITHUB_TOKEN."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test_github_token"}, clear=True):
            assert get_github_token() == "test_github_token"

    def test_get_github_token_preference(self):
        """Test that GH_TOKEN takes precedence over GITHUB_TOKEN."""
        with patch.dict(
            os.environ,
            {"GH_TOKEN": "gh_token", "GITHUB_TOKEN": "github_token"},
            clear=True,
        ):
            assert get_github_token() == "gh_token"

    def test_get_github_token_none(self):
        """Test when no GitHub token is available."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_github_token() is None

    @patch("subprocess.run")
    def test_check_gh_cli_available_true(self, mock_run):
        """Test GitHub CLI availability check when available."""
        mock_run.return_value = MagicMock(returncode=0)
        assert check_gh_cli_available() is True

    @patch("subprocess.run")
    def test_check_gh_cli_available_false_not_found(self, mock_run):
        """Test GitHub CLI availability check when not found."""
        mock_run.side_effect = FileNotFoundError()
        assert check_gh_cli_available() is False

    @patch("subprocess.run")
    def test_check_gh_cli_available_false_error(self, mock_run):
        """Test GitHub CLI availability check when command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ["gh", "--version"])
        assert check_gh_cli_available() is False

    @patch("subprocess.run")
    @patch("silica.remote.utils.github_auth.get_github_token")
    def test_setup_git_credentials_for_github_success(self, mock_get_token, mock_run):
        """Test successful git credentials setup."""
        mock_get_token.return_value = "test_token"
        mock_run.return_value = MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as temp_dir:
            result = setup_git_credentials_for_github(Path(temp_dir))

            assert result is True
            # Should call git commands (remote check, config commands)
            assert mock_run.call_count >= 3  # At least the 3 config commands

    @patch("silica.remote.utils.github_auth.get_github_token")
    def test_setup_git_credentials_for_github_no_token(self, mock_get_token):
        """Test git credentials setup when no token is available."""
        mock_get_token.return_value = None

        result = setup_git_credentials_for_github()

        assert result is False

    @patch("subprocess.run")
    @patch("silica.remote.utils.github_auth.get_github_token")
    def test_setup_git_credentials_for_github_git_error(self, mock_get_token, mock_run):
        """Test git credentials setup when git config fails."""
        mock_get_token.return_value = "test_token"
        mock_run.return_value = MagicMock(returncode=1, stderr="git error")

        result = setup_git_credentials_for_github()

        assert result is False

    @patch("subprocess.run")
    @patch("silica.remote.utils.github_auth.get_github_token")
    @patch("silica.remote.utils.github_auth.check_gh_cli_available")
    def test_setup_github_cli_auth_success_new_auth(
        self, mock_check_gh, mock_get_token, mock_run
    ):
        """Test successful GitHub CLI authentication setup (new authentication)."""
        mock_check_gh.return_value = True
        mock_get_token.return_value = "test_token"

        # Mock auth status check (not authenticated) and successful auth
        mock_run.side_effect = [
            MagicMock(returncode=1),  # auth status - not authenticated
            MagicMock(returncode=0),  # auth login - success
            MagicMock(returncode=0),  # auth setup-git - success
        ]

        success, message = setup_github_cli_auth()

        assert success is True
        assert "authentication and git integration configured" in message

    @patch("subprocess.run")
    @patch("silica.remote.utils.github_auth.get_github_token")
    @patch("silica.remote.utils.github_auth.check_gh_cli_available")
    def test_setup_github_cli_auth_already_authenticated(
        self, mock_check_gh, mock_get_token, mock_run
    ):
        """Test GitHub CLI auth setup when already authenticated."""
        mock_check_gh.return_value = True
        mock_get_token.return_value = "test_token"

        # Mock auth status check (already authenticated) and successful git setup
        mock_run.side_effect = [
            MagicMock(returncode=0),  # auth status - already authenticated
            MagicMock(returncode=0),  # auth setup-git - success
        ]

        success, message = setup_github_cli_auth()

        assert success is True
        assert "already authenticated" in message

    @patch("silica.remote.utils.github_auth.check_gh_cli_available")
    def test_setup_github_cli_auth_no_gh_cli(self, mock_check_gh):
        """Test GitHub CLI auth setup when CLI is not available."""
        mock_check_gh.return_value = False

        success, message = setup_github_cli_auth()

        assert success is False
        assert "GitHub CLI not available" in message

    @patch("silica.remote.utils.github_auth.get_github_token")
    @patch("silica.remote.utils.github_auth.check_gh_cli_available")
    def test_setup_github_cli_auth_no_token(self, mock_check_gh, mock_get_token):
        """Test GitHub CLI auth setup when no token is available."""
        mock_check_gh.return_value = True
        mock_get_token.return_value = None

        success, message = setup_github_cli_auth()

        assert success is False
        assert "No GitHub token found" in message

    @patch("silica.remote.utils.github_auth.setup_github_cli_auth")
    @patch("silica.remote.utils.github_auth.setup_git_credentials_for_github")
    @patch("silica.remote.utils.github_auth.get_github_token")
    @patch("silica.remote.utils.github_auth.check_gh_cli_available")
    def test_setup_github_authentication_prefer_gh_cli(
        self, mock_check_gh, mock_get_token, mock_git_creds, mock_gh_cli_auth
    ):
        """Test GitHub authentication setup preferring GitHub CLI."""
        mock_check_gh.return_value = True
        mock_get_token.return_value = "test_token"
        mock_gh_cli_auth.return_value = (True, "GitHub CLI success")

        success, message = setup_github_authentication(prefer_gh_cli=True)

        assert success is True
        assert "GitHub CLI: GitHub CLI success" in message
        mock_gh_cli_auth.assert_called_once()
        mock_git_creds.assert_not_called()

    @patch("silica.remote.utils.github_auth.setup_github_cli_auth")
    @patch("silica.remote.utils.github_auth.setup_git_credentials_for_github")
    @patch("silica.remote.utils.github_auth.get_github_token")
    @patch("silica.remote.utils.github_auth.check_gh_cli_available")
    def test_setup_github_authentication_fallback_to_git(
        self, mock_check_gh, mock_get_token, mock_git_creds, mock_gh_cli_auth
    ):
        """Test GitHub authentication setup falling back to git credentials."""
        mock_check_gh.return_value = True
        mock_get_token.return_value = "test_token"
        mock_gh_cli_auth.return_value = (False, "GitHub CLI failed")
        mock_git_creds.return_value = True

        success, message = setup_github_authentication(prefer_gh_cli=True)

        assert success is True
        assert "Direct git credentials" in message
        mock_gh_cli_auth.assert_called_once()
        mock_git_creds.assert_called_once()

    @patch("silica.remote.utils.github_auth.setup_git_credentials_for_github")
    @patch("silica.remote.utils.github_auth.get_github_token")
    def test_setup_github_authentication_no_token(self, mock_get_token, mock_git_creds):
        """Test GitHub authentication setup when no token is available."""
        mock_get_token.return_value = None

        success, message = setup_github_authentication()

        assert success is False
        assert "No GitHub token found" in message
        mock_git_creds.assert_not_called()

    @patch("subprocess.run")
    @patch("silica.remote.utils.github_auth.check_gh_cli_available")
    def test_verify_github_authentication_gh_cli_success(self, mock_check_gh, mock_run):
        """Test GitHub authentication verification with GitHub CLI."""
        mock_check_gh.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        success, message = verify_github_authentication()

        assert success is True
        assert "GitHub CLI authentication verified" in message

    @patch("subprocess.run")
    @patch("silica.remote.utils.github_auth.check_gh_cli_available")
    def test_verify_github_authentication_git_success(self, mock_check_gh, mock_run):
        """Test GitHub authentication verification with git."""
        mock_check_gh.return_value = False
        mock_run.return_value = MagicMock(returncode=0)

        success, message = verify_github_authentication()

        assert success is True
        assert "Git HTTPS authentication verified" in message

    @patch("subprocess.run")
    @patch("silica.remote.utils.github_auth.check_gh_cli_available")
    def test_verify_github_authentication_failure(self, mock_check_gh, mock_run):
        """Test GitHub authentication verification failure."""
        mock_check_gh.return_value = False
        mock_run.return_value = MagicMock(returncode=1, stderr="auth failed")

        success, message = verify_github_authentication()

        assert success is False
        assert "authentication verification failed" in message

    @patch("subprocess.run")
    @patch("silica.remote.utils.github_auth.check_gh_cli_available")
    def test_verify_github_authentication_timeout(self, mock_check_gh, mock_run):
        """Test GitHub authentication verification timeout."""
        mock_check_gh.return_value = False
        mock_run.side_effect = subprocess.TimeoutExpired(["git"], 30)

        success, message = verify_github_authentication()

        assert success is False
        assert "timed out" in message
