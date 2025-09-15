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


def setup_git_credentials_for_github(
    directory: Optional[Path] = None, convert_ssh_remote: bool = True
) -> bool:
    """Set up git credentials for GitHub HTTPS authentication using token.

    This configures git to use the GitHub token from environment variables
    for HTTPS authentication with GitHub repositories.

    Args:
        directory: Directory to configure git in (uses current directory if None)
        convert_ssh_remote: Whether to convert SSH remote URLs to HTTPS (default: True)

    Returns:
        True if setup succeeded, False otherwise
    """
    github_token = get_github_token()
    if not github_token:
        logger.warning(
            "No GitHub token found in GH_TOKEN or GITHUB_TOKEN environment variables"
        )
        return False

    original_cwd = None
    try:
        # Change to the specified directory if provided
        if directory:
            original_cwd = os.getcwd()
            os.chdir(directory)

        # Convert SSH remote to HTTPS if requested
        if convert_ssh_remote:
            try:
                # Check if we have a GitHub SSH remote
                result = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0:
                    current_url = result.stdout.strip()
                    if current_url.startswith("git@github.com:"):
                        # Convert to HTTPS
                        https_url = current_url.replace(
                            "git@github.com:", "https://github.com/"
                        )
                        logger.info(
                            f"Converting remote URL from SSH to HTTPS: {current_url} → {https_url}"
                        )

                        subprocess.run(
                            ["git", "remote", "set-url", "origin", https_url],
                            capture_output=True,
                            text=True,
                            timeout=10,
                            check=True,
                        )
                        logger.info("Successfully updated remote URL to HTTPS")
            except Exception as e:
                logger.warning(f"Could not convert SSH remote to HTTPS: {e}")
                # Continue with credential setup anyway

        # Configure git to use the token for GitHub HTTPS authentication
        # This sets up credential helper to use the token for github.com
        config_commands = [
            # Set up credential helper for GitHub
            ["git", "config", "credential.https://github.com.helper", ""],
            ["git", "config", "credential.https://github.com.username", "token"],
            ["git", "config", "credential.https://github.com.password", github_token],
        ]

        for cmd in config_commands:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.warning(f"Git config command failed: {' '.join(cmd)}")
                logger.warning(f"Error: {result.stderr}")
                return False

        logger.info(
            "Successfully configured git credentials for GitHub HTTPS authentication"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to set up git credentials: {e}")
        return False
    finally:
        # Restore original directory
        if original_cwd:
            try:
                os.chdir(original_cwd)
            except OSError:
                pass


def setup_github_cli_auth() -> Tuple[bool, str]:
    """Set up GitHub CLI authentication using token from environment.

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
            # Still set up git integration
            setup_result = subprocess.run(
                ["gh", "auth", "setup-git"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if setup_result.returncode == 0:
                return (
                    True,
                    "GitHub CLI already authenticated and git integration configured",
                )
            else:
                logger.warning(
                    f"Failed to set up git integration: {setup_result.stderr}"
                )
                return True, "GitHub CLI authenticated but git integration setup failed"

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

        # Set up git integration
        setup_result = subprocess.run(
            ["gh", "auth", "setup-git"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if setup_result.returncode != 0:
            logger.warning(f"Git integration setup failed: {setup_result.stderr}")
            return True, "GitHub CLI authenticated but git integration setup failed"

        logger.info(
            "GitHub CLI authentication and git integration configured successfully"
        )
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
    """Set up GitHub authentication using the best available method.

    Args:
        directory: Directory to configure authentication for (uses current directory if None)
        prefer_gh_cli: Whether to prefer GitHub CLI over direct git configuration

    Returns:
        Tuple of (success, message)
    """
    github_token = get_github_token()
    if not github_token:
        # Try to get token from gh CLI if not in environment
        if check_gh_cli_available():
            try:
                result = subprocess.run(
                    ["gh", "auth", "token"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
                github_token = result.stdout.strip()
                if github_token:
                    logger.info("Retrieved GitHub token from gh CLI")
                    # Set in environment for other processes
                    import os

                    os.environ["GH_TOKEN"] = github_token
                    os.environ["GITHUB_TOKEN"] = github_token
                else:
                    return (False, "No GitHub token available from gh CLI")
            except (
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
                FileNotFoundError,
            ):
                return (False, "Could not retrieve GitHub token from gh CLI")
        else:
            return (
                False,
                "No GitHub token found in environment variables and gh CLI not available",
            )

    # Use ONLY ONE authentication method to avoid conflicts
    if prefer_gh_cli and check_gh_cli_available():
        # Try GitHub CLI method
        success, message = setup_github_cli_auth()
        if success:
            return True, f"GitHub CLI: {message}"
        else:
            # If GitHub CLI fails, fall back to direct git configuration
            logger.warning(
                f"GitHub CLI setup failed: {message}, trying direct git configuration"
            )
            if setup_git_credentials_for_github(directory, convert_ssh_remote=True):
                return (
                    True,
                    "Fallback to direct git credentials: GitHub authentication configured",
                )
            else:
                return (
                    False,
                    f"Both GitHub CLI and direct git configuration failed: {message}",
                )
    else:
        # Use direct git credential configuration only
        if setup_git_credentials_for_github(directory, convert_ssh_remote=True):
            return True, "Direct git credentials: GitHub authentication configured"
        else:
            return (
                False,
                "Failed to configure GitHub authentication via git credentials",
            )


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
