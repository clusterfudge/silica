"""Python implementation of the piku client script.

This module provides a direct implementation of the piku bash script in Python,
with the ability to suppress the headers printed to stdout.
"""

import os
import sys
import subprocess
import platform
from typing import Optional, List, Union


def run_piku(
    command: str,
    args: Optional[List[str]] = None,
    remote: Optional[str] = None,
    suppress_headers: bool = True,
    exec_mode: bool = False,
) -> Union[int, subprocess.CompletedProcess]:
    """Run a piku command with the given arguments.

    This function emulates the behavior of the piku bash script, with the option
    to suppress the headers printed to stdout.

    Args:
        command: The piku command to run (e.g., "status", "logs", "shell")
        args: Optional list of arguments for the command
        remote: Optional remote name (defaults to "piku")
        suppress_headers: Whether to suppress the "Piku remote operator" headers
        exec_mode: Whether to replace the current process for interactive commands

    Returns:
        If exec_mode is True, returns the exit code.
        Otherwise, returns a CompletedProcess instance.
    """
    if args is None:
        args = []

    # Determine SSH command based on platform (similar to the bash script)
    ssh_cmd = "ssh.exe" if "microsoft" in platform.uname().release.lower() else "ssh"

    # Get the git remote URL for the specified remote
    remote_name = remote or "piku"
    git_remote = get_git_remote(remote_name)

    # Fall back to environment variables if no git remote found
    if not git_remote:
        server = os.environ.get("PIKU_SERVER", "")
        app = os.environ.get("PIKU_APP", "")
        remote_str = f"{server}:{app}" if server and app else ""
    else:
        remote_str = git_remote

    # Handle empty or malformed remote
    if not remote_str or remote_str == ":":
        if not suppress_headers:
            print("", file=sys.stderr)
            print("Error: no piku server configured.", file=sys.stderr)
            print(
                "Use PIKU_SERVER=piku@MYSERVER.NET or configure a git remote called 'piku'.",
                file=sys.stderr,
            )
            print("", file=sys.stderr)
        return 1

    # Parse the remote string to get server and app
    parts = remote_str.split(":", 1)
    server = parts[0]
    app = parts[1] if len(parts) > 1 else ""

    # Handling special case for init command
    if command == "init":
        return handle_init_command(git_remote)

    # Print headers to stderr (unless suppressed)
    if not suppress_headers:
        print("Piku remote operator.", file=sys.stderr)
        print(f"Server: {server}", file=sys.stderr)
        print(f"App: {app}", file=sys.stderr)
        print("", file=sys.stderr)

    # Handle different commands
    if not command or command == "help":
        # Special case for help command
        return handle_help_command(ssh_cmd, server, [command] if command else [])

    elif command in ["apps", "setup", "setup:ssh", "update"]:
        # Direct server commands
        ssh_args = [ssh_cmd, server, command] + args
        return run_subprocess(ssh_args, exec_mode)

    elif command == "shell":
        # Shell command
        ssh_args = [ssh_cmd, "-t", server, "run", app, "bash"]
        return run_subprocess(ssh_args, exec_mode)

    elif command == "tmux":
        # Tmux command - including -- to prevent Click from parsing arguments
        ssh_args = [
            ssh_cmd,
            "-t",
            server,
            "run",
            app,
            "tmux",
            "--",
            "new-session",
            "-A",
            "-s",
            app,
        ]
        return run_subprocess(ssh_args, exec_mode)

    elif command == "download":
        # Download command
        remote_file = args[0] if args else ""
        local_path = args[1] if len(args) > 1 else "."
        scp_args = ["scp", f"{server}:~/.piku/apps/{app}/{remote_file}", local_path]
        return run_subprocess(scp_args, exec_mode)

    else:
        # Default case - all other commands
        ssh_args = [ssh_cmd, server, command, app] + args
        return run_subprocess(ssh_args, exec_mode)


def run_subprocess(
    args: List[str], exec_mode: bool = False
) -> Union[int, subprocess.CompletedProcess]:
    """Run a subprocess with the given arguments.

    Args:
        args: List of arguments to pass to the subprocess
        exec_mode: Whether to replace the current process

    Returns:
        If exec_mode is True, returns the exit code.
        Otherwise, returns a CompletedProcess instance.
    """
    if exec_mode:
        # Replace the current process - use for interactive commands
        try:
            os.execvp(args[0], args)
        except OSError as e:
            print(f"Error executing {args[0]}: {e}", file=sys.stderr)
            return 1
    else:
        # Run as a subprocess and return the result
        try:
            return subprocess.run(args, check=False, text=True)
        except subprocess.SubprocessError as e:
            print(f"Error running subprocess: {e}", file=sys.stderr)
            return subprocess.CompletedProcess(
                args=args, returncode=1, stdout="", stderr=str(e)
            )


def get_git_remote(remote_name: str) -> str:
    """Get the git remote URL for the specified remote.

    Args:
        remote_name: The name of the git remote

    Returns:
        The git remote URL, or an empty string if not found
    """
    try:
        result = subprocess.run(
            ["git", "config", "--get", f"remote.{remote_name}.url"],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def handle_init_command(git_remote: str) -> int:
    """Handle the init command to create ENV and Procfile.

    Args:
        git_remote: The git remote URL

    Returns:
        Exit code
    """
    github_home = "https://raw.githubusercontent.com/piku/piku/master/"

    # Check if ENV file already exists
    if os.path.exists("ENV"):
        print("ENV file already exists.")
    else:
        try:
            subprocess.run(
                ["curl", "-s", f"{github_home}examples/ENV", "-o", "ENV"], check=True
            )
            print("Wrote ./ENV file.")
        except subprocess.SubprocessError:
            print("Failed to download ENV file.")
            return 1

    # Check if Procfile already exists
    if os.path.exists("Procfile"):
        print("Procfile already exists.")
    else:
        try:
            subprocess.run(
                ["curl", "-s", f"{github_home}examples/Procfile", "-o", "Procfile"],
                check=True,
            )
            print("Wrote ./Procfile.")
        except subprocess.SubprocessError:
            print("Failed to download Procfile.")
            return 1

    # If no git remote, provide instructions
    if not git_remote:
        print("Now set up your piku remote for this app:")
        print("git remote add piku piku@HOSTNAME:APPNAME")

    return 0


def handle_help_command(
    ssh_cmd: str, server: str, args: List[str]
) -> Union[int, subprocess.CompletedProcess]:
    """Handle the help command.

    Args:
        ssh_cmd: The SSH command to use
        server: The server to connect to
        args: Additional arguments

    Returns:
        CompletedProcess instance with command results
    """
    result = subprocess.run(
        [ssh_cmd, "-o", "LogLevel=QUIET", server] + args,
        check=False,
        capture_output=True,
        text=True,
    )

    # Filter out internal commands
    for line in result.stdout.splitlines():
        if "INTERNAL" not in line:
            print(line)

    # Print local commands
    print("  shell             Local command to start an SSH session in the remote.")
    print(
        "  tmux              Local command to start or attach to a tmux session for the app."
    )
    print("  init              Local command to download an example ENV and Procfile.")
    print(
        "  download          Local command to scp down a remote file. args: REMOTE-FILE(s) LOCAL-PATH"
    )
    print("                    Remote file path is relative to the app folder.")

    return result


# Convenience functions that map directly to common piku commands


def status(
    app_name: Optional[str] = None, remote: Optional[str] = None
) -> subprocess.CompletedProcess:
    """Check the status of an application.

    Args:
        app_name: Optional app name (if None, determined from remote)
        remote: Optional remote name (defaults to "piku")

    Returns:
        CompletedProcess instance with command results
    """
    args = [app_name] if app_name else []
    return run_piku("status", args, remote, suppress_headers=True)


def logs(
    app_name: Optional[str] = None,
    tail: Optional[int] = None,
    follow: bool = False,
    remote: Optional[str] = None,
) -> Union[int, subprocess.CompletedProcess]:
    """Get logs for an application.

    Args:
        app_name: Optional app name (if None, determined from remote)
        tail: Number of log lines to show
        follow: Whether to follow the logs
        remote: Optional remote name (defaults to "piku")

    Returns:
        If follow is True, returns the exit code.
        Otherwise, returns a CompletedProcess instance.
    """
    args = []
    if app_name:
        args.append(app_name)
    if tail is not None:
        args.append(str(tail))

    return run_piku("logs", args, remote, suppress_headers=True, exec_mode=follow)


def shell(
    app_name: Optional[str] = None,
    command: Optional[str] = None,
    remote: Optional[str] = None,
) -> Union[int, subprocess.CompletedProcess]:
    """Start a shell session for an application.

    Args:
        app_name: Optional app name (if None, determined from remote)
        command: Optional command to run in the shell
        remote: Optional remote name (defaults to "piku")

    Returns:
        If command is None, returns the exit code.
        Otherwise, returns a CompletedProcess instance.
    """
    # If a command is provided, we need to wrap it in a custom command
    # that runs the command and then exits
    exec_mode = command is None

    if command:
        # Create a custom shell command that runs the command and exits
        raise NotImplementedError("Command execution in shell is not yet implemented")

    return run_piku(
        "shell",
        [app_name] if app_name else [],
        remote,
        suppress_headers=True,
        exec_mode=exec_mode,
    )


def tmux(
    app_name: Optional[str] = None,
    remote: Optional[str] = None,
) -> int:
    """Start or attach to a tmux session for an application.

    Args:
        app_name: Optional app name (if None, determined from remote)
        remote: Optional remote name (defaults to "piku")

    Returns:
        Exit code
    """
    return run_piku(
        "tmux",
        [app_name] if app_name else [],
        remote,
        suppress_headers=True,
        exec_mode=True,
    )


def agent_session(
    app_name: Optional[str] = None,
    script_path: str = "./AGENT.sh",
    remote: Optional[str] = None,
) -> int:
    """Connect to the agent tmux session.

    This is similar to the tmux command, but creates a session running the agent script.

    Args:
        app_name: Optional app name (if None, determined from remote)
        script_path: Path to the agent script
        remote: Optional remote name (defaults to "piku")

    Returns:
        Exit code
    """
    # This is a custom command that isn't part of the original piku script
    # We'll implement it based on the tmux command, but with a custom session command
    # TODO: Implement this function
    raise NotImplementedError("Agent session is not yet implemented")
