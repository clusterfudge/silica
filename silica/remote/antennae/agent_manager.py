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
                if line.startswith(session_name + " "):
                    parts = line.split()
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
            # The session will run the agent and then keep bash open for debugging
            tmux_command = [
                "tmux",
                "new-session",
                "-d",
                "-s",
                session_name,
                "-c",
                str(self.config.get_code_directory()),
                f"bash -c '{agent_command}; exec bash'",
            ]

            subprocess.run(tmux_command, check=True)
            return True

        except (subprocess.CalledProcessError, FileNotFoundError):
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

        This method is idempotent - always cleans and re-clones to ensure fresh state.

        Args:
            repo_url: URL of the repository to clone
            branch: Branch to checkout (default: main)

        Returns:
            True if cloned successfully, False otherwise
        """
        try:
            # Always clean and re-clone for idempotent behavior
            if self.config.get_code_directory().exists():
                shutil.rmtree(self.config.get_code_directory())

            self.config.ensure_code_directory()

            # Clone the repository
            git.Repo.clone_from(
                repo_url, self.config.get_code_directory(), branch=branch
            )

            return True

        except (GitCommandError, Exception):
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
            import logging

            logger = logging.getLogger(__name__)
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
            Dictionary with workspace status information
        """
        tmux_info = self.get_tmux_session_info()

        return {
            "workspace_name": self.config.get_workspace_name(),
            "code_directory": str(self.config.get_code_directory()),
            "code_directory_exists": self.config.get_code_directory().exists(),
            "tmux_session": {
                "running": self.is_tmux_session_running(),
                "info": tmux_info,
            },
            "agent_command": self.config.get_agent_command(),
        }

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
