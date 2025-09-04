"""Agent management for antennae webapp.

Handles tmux session lifecycle and silica developer agent management for a
single workspace.
"""

import subprocess
import os
import shutil
from typing import Dict, Any, Optional
import git
from git.exc import GitCommandError

from .config import config

import logging

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages tmux sessions and silica developer agent for a workspace."""

    def __init__(self):
        """Initialize the agent manager."""
        self.config = config

    def is_tmux_session_running(self) -> bool:
        """Check if the tmux session is currently running.

        Returns:
            True if session exists, False otherwise
        """
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", self.config.get_tmux_session_name()],
                capture_output=True,
                check=False,
            )
            return result.returncode == 0
        except FileNotFoundError:
            # tmux not installed
            return False

    def get_tmux_session_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the current tmux session.

        Returns:
            Dictionary with session information, or None if not running
        """
        if not self.is_tmux_session_running():
            return None

        try:
            # Get all sessions and filter for our session
            result = subprocess.run(
                [
                    "tmux",
                    "list-sessions",
                    "-F",
                    "#{session_name} #{session_windows} #{session_created} #{?session_attached,attached,detached}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            # Find our session in the output
            session_name = self.config.get_tmux_session_name()
            for line in result.stdout.strip().split("\n"):
                if line.strip():  # Skip empty lines
                    parts = line.strip().split()
                    if len(parts) > 0 and parts[0] == session_name:
                        return {
                            "session_name": parts[0],
                            "windows": parts[1] if len(parts) > 1 else "1",
                            "created": parts[2] if len(parts) > 2 else "unknown",
                            "status": parts[3] if len(parts) > 3 else "unknown",
                        }
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return None

    def start_tmux_session(self) -> bool:
        """Start a tmux session with the silica developer agent.

        This method is idempotent:
        - If session exists, preserves it and returns True (avoids killing active agents)
        - If no session exists, creates a new one with the agent

        Returns:
            True if session started successfully or already exists, False otherwise
        """
        # If session already exists, use it (don't kill active agent sessions)
        if self.is_tmux_session_running():
            return True

        try:
            session_name = self.config.get_tmux_session_name()
            agent_command = self.config.get_agent_command()

            # Create tmux session in detached mode, starting in code directory
            # First create the session with a basic shell
            tmux_create_command = [
                "tmux",
                "new-session",
                "-d",
                "-s",
                session_name,
                "-c",
                str(self.config.get_code_directory()),
            ]

            subprocess.run(tmux_create_command, check=True)

            # Then send the agent command to the session
            # This ensures proper terminal environment within tmux
            tmux_send_command = [
                "tmux",
                "send-keys",
                "-t",
                session_name,
                agent_command,
                "C-m",
            ]

            subprocess.run(tmux_send_command, check=True)

            return True

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"Failed to start tmux session: {e}")
            return False

    def stop_tmux_session(self) -> bool:
        """Stop the tmux session.

        Returns:
            True if session stopped successfully, False otherwise
        """
        if not self.is_tmux_session_running():
            return True  # Already stopped

        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", self.config.get_tmux_session_name()],
                check=True,
            )
            return True

        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def send_message_to_session(self, message: str) -> bool:
        """Send a message to the tmux session.

        Args:
            message: Message to send to the agent

        Returns:
            True if message sent successfully, False otherwise
        """
        if not self.is_tmux_session_running():
            return False

        try:
            # Send keys to the tmux session
            subprocess.run(
                [
                    "tmux",
                    "send-keys",
                    "-t",
                    self.config.get_tmux_session_name(),
                    message,
                    "C-m",  # C-m sends Enter
                ],
                check=True,
            )
            return True

        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def clone_repository(self, repo_url: str, branch: str = "main") -> bool:
        """Clone a repository to the code directory.

        This method preserves local changes:
        - If no repo exists, clones fresh
        - If repo exists and is clean, leaves it alone
        - If repo exists but has different remote/branch, reports status but doesn't destroy

        Args:
            repo_url: URL of the repository to clone
            branch: Branch to checkout (default: main)

        Returns:
            True if repository is ready, False otherwise
        """
        code_dir = self.config.get_code_directory()

        try:
            # If code directory doesn't exist, clone fresh
            if not code_dir.exists():
                self.config.ensure_code_directory()
                git.Repo.clone_from(repo_url, code_dir, branch=branch)
                return True

            # If code directory exists but no .git, clone fresh
            if not (code_dir / ".git").exists():
                shutil.rmtree(code_dir)
                self.config.ensure_code_directory()
                git.Repo.clone_from(repo_url, code_dir, branch=branch)
                return True

            # Repository already exists - check its state
            repo = git.Repo(code_dir)

            # Check if the repository matches what we want
            current_remote_urls = [
                remote.url for remote in repo.remotes if remote.name == "origin"
            ]
            if not current_remote_urls or current_remote_urls[0] != repo_url:
                # Different remote URL - don't destroy, just report it exists
                logger.info(
                    f"Repository exists with different remote: {current_remote_urls[0] if current_remote_urls else 'none'} vs {repo_url}"
                )
                return True  # Still usable, just different remote

            # Check if we're on the right branch
            try:
                current_branch = repo.active_branch.name
                if current_branch != branch:
                    logger.info(
                        f"Repository on different branch: {current_branch} vs {branch}"
                    )
                    # Could checkout the branch here, but safer to leave it alone
            except Exception:
                # Detached HEAD or other state - that's okay
                pass

            # Repository exists and looks compatible
            return True

        except (GitCommandError, Exception) as e:
            logger.error(f"Repository setup error: {e}")
            return False

    def setup_environment(self) -> bool:
        """Setup the development environment in the code directory.

        This method is idempotent - can be called multiple times safely.

        Returns:
            True if setup successful, False otherwise
        """
        if not self.config.get_code_directory().exists():
            return False

        try:
            # Change to code directory for setup
            original_cwd = os.getcwd()
            os.chdir(self.config.get_code_directory())

            # Run uv sync to install dependencies
            subprocess.run(["uv", "sync"], capture_output=True, check=True, text=True)

            return True

        except subprocess.CalledProcessError as e:
            # Log the specific error for debugging
            logger.error(
                f"Environment setup failed: {e.stderr if e.stderr else str(e)}"
            )
            return False
        except FileNotFoundError:
            # uv not installed
            return False
        finally:
            # Always restore original working directory
            try:
                os.chdir(original_cwd)
            except OSError:
                pass

    def cleanup_workspace(self) -> bool:
        """Clean up the workspace by stopping sessions and removing files.

        Returns:
            True if cleanup successful, False otherwise
        """
        success = True

        # Stop tmux session
        if not self.stop_tmux_session():
            success = False

        # Remove code directory
        try:
            if self.config.get_code_directory().exists():
                shutil.rmtree(self.config.get_code_directory())
        except Exception:
            success = False

        return success

    def get_workspace_status(self) -> Dict[str, Any]:
        """Get comprehensive status of the workspace.

        Returns:
            Dictionary with workspace status information including repository state
        """
        tmux_info = self.get_tmux_session_info()
        repo_info = self._get_repository_info()

        return {
            "workspace_name": self.config.get_workspace_name(),
            "code_directory": str(self.config.get_code_directory()),
            "code_directory_exists": self.config.get_code_directory().exists(),
            "repository": repo_info,
            "tmux_session": {
                "running": self.is_tmux_session_running(),
                "info": tmux_info,
            },
            "agent_command": self.config.get_agent_command(),
        }

    def _get_repository_info(self) -> Dict[str, Any]:
        """Get detailed repository information including branch and dirty state.

        Returns:
            Dictionary with repository status information
        """
        code_dir = self.config.get_code_directory()

        repo_info = {
            "exists": False,
            "is_git_repo": False,
            "branch": None,
            "is_dirty": False,
            "remote_url": None,
            "ahead_behind": {"ahead": 0, "behind": 0},
            "status": "unknown",
        }

        if not code_dir.exists():
            repo_info["status"] = "no_code_directory"
            return repo_info

        repo_info["exists"] = True

        if not (code_dir / ".git").exists():
            repo_info["status"] = "not_git_repo"
            return repo_info

        repo_info["is_git_repo"] = True

        try:
            repo = git.Repo(code_dir)

            # Get current branch
            try:
                repo_info["branch"] = repo.active_branch.name
            except Exception:
                # Detached HEAD or other state
                try:
                    repo_info["branch"] = repo.head.commit.hexsha[:8]
                except Exception:
                    repo_info["branch"] = "unknown"

            # Check if repository is dirty (has uncommitted changes or untracked files)
            repo_info["is_dirty"] = repo.is_dirty(untracked_files=True)

            # Get remote URL
            try:
                origin = repo.remote("origin")
                repo_info["remote_url"] = origin.url
            except Exception:
                repo_info["remote_url"] = None

            # Get ahead/behind status relative to remote
            try:
                if repo_info["remote_url"] and not repo.is_dirty():
                    # Only check ahead/behind if we have a clean repo
                    tracking_branch = repo.active_branch.tracking_branch()
                    if tracking_branch:
                        ahead, behind = repo.git.rev_list(
                            "--count",
                            "--left-right",
                            f"{tracking_branch}...{repo.active_branch}",
                        ).split("\t")
                        repo_info["ahead_behind"] = {
                            "ahead": int(behind),  # Note: rev-list returns behind first
                            "behind": int(ahead),  # and ahead second with --left-right
                        }
            except Exception:
                # If we can't determine ahead/behind, leave as 0,0
                pass

            # Determine overall status
            if repo_info["is_dirty"]:
                repo_info["status"] = "dirty"
            elif repo_info["ahead_behind"]["ahead"] > 0:
                repo_info["status"] = "ahead"
            elif repo_info["ahead_behind"]["behind"] > 0:
                repo_info["status"] = "behind"
            else:
                repo_info["status"] = "clean"

        except Exception:
            repo_info["status"] = "error"

        return repo_info

    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection information for direct tmux access.

        Returns:
            Dictionary with connection details
        """
        return {
            "session_name": self.config.get_tmux_session_name(),
            "working_directory": str(self.config.get_working_directory()),
            "code_directory": str(self.config.get_code_directory()),
            "tmux_running": self.is_tmux_session_running(),
        }


# Global agent manager instance
agent_manager = AgentManager()
