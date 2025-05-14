"""Direct implementation of piku commands without using the piku script.

This module provides a direct implementation of the most common piku commands,
bypassing the piku client script to avoid the headers printed to stdout.
"""

import os
import subprocess
from typing import Optional, List, Union, Tuple


def get_remote_info(workspace_name: str) -> Tuple[str, str]:
    """Get the server connection and app name from the git remote.

    This follows the same approach as the piku script: parse the git remote URL
    and extract the server connection and app name.

    Args:
        workspace_name: Name of the workspace (git remote)

    Returns:
        Tuple of (server_connection, app_name)
    """
    try:
        # Get the git remote URL for the workspace
        result = subprocess.run(
            f"git config --get remote.{workspace_name}.url",
            shell=True,
            check=True,
            capture_output=True,
            text=True,
        )
        remote_url = result.stdout.strip()

        # If we have a remote URL, split it at the colon
        if remote_url and ":" in remote_url:
            server, app = remote_url.split(":", 1)

            # IMPORTANT: Ensure the server has the piku user
            if "@" not in server:
                server = "piku@" + server

            # Strip .git suffix if present
            if app.endswith(".git"):
                app = app[:-4]
            return server, app

        # Fall back to environment variables or defaults
        server = os.environ.get("PIKU_SERVER", "piku")
        # IMPORTANT: Ensure the server has the piku user
        if "@" not in server:
            server = "piku@" + server

        app = os.environ.get("PIKU_APP", workspace_name)
        return server, app

    except subprocess.CalledProcessError:
        # If git command fails, return default with piku user
        return "piku@localhost", workspace_name


def direct_ssh_command(
    server: str, command: str, interactive: bool = True, capture_output: bool = False
) -> Union[subprocess.CompletedProcess, int]:
    """Run a command on the remote server via SSH.

    Args:
        server: SSH connection string (e.g., "piku@host")
        command: Command to run on the remote server
        interactive: Whether to run in interactive mode (-t flag)
        capture_output: Whether to capture the output

    Returns:
        CompletedProcess instance with command results or return code
    """
    ssh_cmd = ["ssh"]
    if interactive:
        ssh_cmd.append("-t")

    ssh_cmd.extend([server, command])

    if not capture_output and interactive:
        # For interactive commands, use os.execvp to replace the current process
        # This ensures proper handling of stdin/stdout/stderr
        return os.execvp("ssh", ssh_cmd)
    else:
        # For non-interactive commands or when capturing output
        return subprocess.run(
            ssh_cmd, check=False, capture_output=capture_output, text=True
        )


def shell(
    workspace_name: str, command: Optional[str] = None, capture_output: bool = False
) -> Union[subprocess.CompletedProcess, int]:
    """Access the shell for the application.

    Args:
        workspace_name: Name of the workspace (git remote)
        command: Optional command to run in the shell
        capture_output: Whether to capture the output

    Returns:
        CompletedProcess instance with command results or return code
    """
    server, app_name = get_remote_info(workspace_name)

    if command:
        # Single command mode
        remote_cmd = f"run {app_name} bash -c '{command}'"
        return direct_ssh_command(
            server, remote_cmd, interactive=True, capture_output=capture_output
        )
    else:
        # Interactive shell mode
        remote_cmd = f"run {app_name} bash"
        return direct_ssh_command(
            server, remote_cmd, interactive=True, capture_output=False
        )


def tmux(workspace_name: str, tmux_args: Optional[List[str]] = None) -> int:
    """Access the tmux session for the application.

    Args:
        workspace_name: Name of the workspace (git remote)
        tmux_args: Optional tmux arguments

    Returns:
        Return code from the command
    """
    server, app_name = get_remote_info(workspace_name)

    # From the original piku script:
    # $SSH -t "$server" run "$app" tmux -- new-session -A -s "$app"
    # The correct command to create/attach to tmux session with -- to prevent Click from parsing args
    if not tmux_args:
        # Default command is to create/attach to the app session
        remote_cmd = f"run {app_name} tmux -- new-session -A -s {app_name}"
    else:
        # Run with specified arguments
        tmux_cmd = " ".join(tmux_args)
        remote_cmd = f"run {app_name} tmux -- {tmux_cmd}"

    return direct_ssh_command(
        server, remote_cmd, interactive=True, capture_output=False
    )


def agent_session(workspace_name: str, script_path: str = "./AGENT.sh") -> int:
    """Connect to the agent tmux session.

    Args:
        workspace_name: Name of the workspace (git remote)
        script_path: Path to the agent script relative to app directory

    Returns:
        Return code from the command
    """
    server, app_name = get_remote_info(workspace_name)

    # Create/attach to tmux session with AGENT.sh script
    # Important: Use -- to prevent Click from parsing the tmux arguments
    remote_cmd = f"run {app_name} tmux -- new-session -A -s {app_name} '{script_path}; exec bash'"

    return direct_ssh_command(
        server, remote_cmd, interactive=True, capture_output=False
    )


def run_command(
    command: str,
    workspace_name: str,
    app_name: Optional[str] = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess:
    """Run a piku command on the remote server.

    Args:
        command: Piku command to run (e.g., "status", "logs")
        workspace_name: Name of the workspace (git remote)
        app_name: Optional app name (if not provided, will be derived from workspace)
        capture_output: Whether to capture the output

    Returns:
        CompletedProcess instance with command results
    """
    server, derived_app_name = get_remote_info(workspace_name)

    if app_name is None:
        app_name = derived_app_name

    # For standard piku commands (not shell or tmux)
    remote_cmd = f"{command} {app_name}"

    return direct_ssh_command(
        server,
        remote_cmd,
        interactive=not capture_output,
        capture_output=capture_output,
    )
