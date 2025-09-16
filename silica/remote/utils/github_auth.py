"""GitHub authentication utilities for silica remote operations."""

import os
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def get_github_token() -> Optional[str]:
    """Get GitHub token from environment variables.

    Checks both GH_TOKEN and GITHUB_TOKEN (with GH_TOKEN taking precedence).
    This is expected to be called in contexts where environment variables
    should already be set up properly (e.g., remote agent sessions).

    Returns:
        GitHub token string or None if not found
    """
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def check_gh_cli_available() -> bool:
    """Check if GitHub CLI (gh) is available.

    Returns:
        True if gh CLI is available, False otherwise
    """
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.returncode == 0
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return False


def setup_github_cli_auth() -> Tuple[bool, str]:
    """Set up GitHub CLI authentication using token from environment and configure git integration.

    This requires GH_TOKEN or GITHUB_TOKEN to be set in environment variables.
    After authentication, runs 'gh auth setup-git' to configure git credential helper.

    Returns:
        Tuple of (success, message)
    """
    if not check_gh_cli_available():
        return False, "GitHub CLI not available"

    github_token = get_github_token()
    if not github_token:
        return (
            False,
            "No GitHub token found in GH_TOKEN or GITHUB_TOKEN environment variables",
        )

    try:
        # Check if already authenticated
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            logger.info("GitHub CLI already authenticated")
        else:
            # Authenticate using the token
            auth_process = subprocess.run(
                ["gh", "auth", "login", "--with-token"],
                input=github_token,
                text=True,
                capture_output=True,
                timeout=30,
            )

            if auth_process.returncode != 0:
                error_msg = f"GitHub CLI authentication failed: {auth_process.stderr}"
                logger.error(error_msg)
                return False, error_msg

            logger.info("GitHub CLI authenticated successfully")

        # Always set up git integration (this is the key step)
        setup_result = subprocess.run(
            ["gh", "auth", "setup-git"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if setup_result.returncode != 0:
            error_msg = f"Git integration setup failed: {setup_result.stderr}"
            logger.error(error_msg)
            return False, error_msg

        logger.info("GitHub CLI git integration configured successfully")
        return True, "GitHub CLI authentication and git integration configured"

    except subprocess.TimeoutExpired:
        return False, "GitHub CLI authentication timed out"
    except Exception as e:
        error_msg = f"GitHub CLI authentication error: {e}"
        logger.error(error_msg)
        return False, error_msg


def setup_github_authentication(
    directory: Optional[Path] = None, prefer_gh_cli: bool = True
) -> Tuple[bool, str]:
    """Set up GitHub authentication using GitHub CLI only.

    This function requires GH_TOKEN or GITHUB_TOKEN environment variables to be set.
    It uses 'gh auth login --with-token' followed by 'gh auth setup-git' to configure
    git credential helper properly. No fallback mechanisms are provided.

    Args:
        directory: Directory parameter kept for API compatibility (not used)
        prefer_gh_cli: Kept for API compatibility, but only GitHub CLI method is supported

    Returns:
        Tuple of (success, message)
    """
    # Check for required environment token
    github_token = get_github_token()
    if not github_token:
        return (
            False,
            "No GitHub token found in GH_TOKEN or GITHUB_TOKEN environment variables. "
            "These are required for GitHub authentication.",
        )

    # Check if GitHub CLI is available
    if not check_gh_cli_available():
        return (
            False,
            'GitHub CLI not available. Install with: curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null && sudo apt update && sudo apt install gh',
        )

    # Set up GitHub CLI authentication and git integration
    success, message = setup_github_cli_auth()
    if success:
        return True, message
    else:
        return False, f"GitHub authentication failed: {message}"


def verify_github_authentication(
    test_repo: str = "octocat/Hello-World",
) -> Tuple[bool, str]:
    """Verify that GitHub authentication is working by testing repository access.

    Args:
        test_repo: GitHub repository to test access with (should be public)

    Returns:
        Tuple of (success, message)
    """
    try:
        # Test with GitHub CLI if available
        if check_gh_cli_available():
            result = subprocess.run(
                ["gh", "repo", "view", test_repo],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return (
                    True,
                    f"GitHub CLI authentication verified (accessed {test_repo})",
                )
            else:
                logger.warning(f"GitHub CLI test failed: {result.stderr}")

        # Test with git clone (dry run)
        result = subprocess.run(
            ["git", "ls-remote", f"https://github.com/{test_repo}.git"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            return True, f"Git HTTPS authentication verified (accessed {test_repo})"
        else:
            return False, f"GitHub authentication verification failed: {result.stderr}"

    except subprocess.TimeoutExpired:
        return False, "GitHub authentication verification timed out"
    except Exception as e:
        return False, f"GitHub authentication verification error: {e}"
