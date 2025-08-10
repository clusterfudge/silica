"""
TmuxTool - Persistent shell session management using tmux.

This module provides tools for creating, managing, and interacting with
persistent shell sessions that survive across tool invocations.
"""

import re
from typing import Optional

from silica.developer.context import AgentContext
from silica.developer.sandbox import DoSomethingElseError
from .framework import tool
from .tmux_session import get_session_manager


def _check_tmux_available() -> bool:
    """Check if tmux is available on the system."""
    import subprocess

    try:
        result = subprocess.run(["tmux", "-V"], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _validate_command_safety(command: str) -> bool:
    """Validate that a command is safe to execute (reuse logic from bash tool)."""
    dangerous_commands = [
        r"\bsudo\b",
        r"\brm\s+(-rf|--recursive.*--force)",
        r"\bchmod\s+777",
        r"\bchown\s+.*root",
    ]

    for dangerous_cmd in dangerous_commands:
        if re.search(dangerous_cmd, command, re.IGNORECASE):
            return False

    return True


@tool
def tmux_create_session(
    context: "AgentContext", session_name: str, initial_command: Optional[str] = None
) -> str:
    """Create a new tmux session with optional initial command.

    Creates a persistent shell session that will survive across tool invocations.
    Sessions can be used for background processes, long-running tasks, or
    maintaining shell state.

    Args:
        session_name: Name for the session (alphanumeric, underscore, dash only)
        initial_command: Optional command to run immediately in the session
    """
    # Check if tmux is available
    if not _check_tmux_available():
        return "Error: tmux is not available on this system. Please install tmux to use this tool."

    # Validate session name
    if not session_name or not re.match(r"^[a-zA-Z0-9_-]+$", session_name):
        return "Error: Invalid session name. Use only alphanumeric characters, underscores, and hyphens."

    # Check permissions for session creation
    try:
        if not context.sandbox.check_permissions("tmux_create_session", session_name):
            return "Error: Permission denied for session creation."
    except DoSomethingElseError:
        raise

    # Validate initial command if provided
    if initial_command:
        if not _validate_command_safety(initial_command):
            return "Error: Initial command contains potentially dangerous operations."

        try:
            if not context.sandbox.check_permissions("shell", initial_command):
                return "Error: Permission denied for initial command."
        except DoSomethingElseError:
            raise

    # Create the session
    session_manager = get_session_manager()
    success, message = session_manager.create_session(session_name, initial_command)

    return message


@tool
def tmux_list_sessions(context: "AgentContext") -> str:
    """List all active tmux sessions with their status and activity.

    Shows information about all managed tmux sessions including:
    - Session name
    - Status (active/inactive)
    - Creation time
    - Last activity
    - Number of commands executed

    Returns:
        Formatted table of session information
    """
    # Check if tmux is available
    if not _check_tmux_available():
        return "Error: tmux is not available on this system."

    session_manager = get_session_manager()
    sessions = session_manager.list_sessions()

    if not sessions:
        return "No tmux sessions found."

    # Format as table
    result = "## Active Tmux Sessions\n\n"
    result += "| Name | Status | Created | Last Activity | Commands |\n"
    result += "|------|--------|---------|---------------|----------|\n"

    for session in sessions:
        created_time = session["created_at"][:16].replace("T", " ")
        last_activity = session["last_activity"][:16].replace("T", " ")

        result += f"| {session['name']} | {session['status']} | {created_time} | {last_activity} | {session['commands_executed']} |\n"

    return result


@tool
def tmux_execute_command(
    context: "AgentContext",
    session_name: str,
    command: str,
    capture_output: bool = True,
    timeout: Optional[int] = None,
    timeout_action: str = "interrupt",
    refresh_env: bool = False,
) -> str:
    """Execute a command in a specific tmux session.

    Sends a command to an existing tmux session. The command will be executed
    in the session's current context and environment.

    Args:
        session_name: Name of the target session
        command: Command to execute
        capture_output: Whether to capture and return recent output after execution
        timeout: Optional timeout in seconds (None for no timeout)
        timeout_action: Action to take on timeout ('interrupt', 'kill', 'terminate')
        refresh_env: Whether to refresh environment variables before executing command
    """
    # Check if tmux is available
    if not _check_tmux_available():
        return "Error: tmux is not available on this system."

    # Validate command safety
    if not _validate_command_safety(command):
        return "Error: Command contains potentially dangerous operations."

    # Check permissions
    try:
        if not context.sandbox.check_permissions("shell", command):
            return "Error: Permission denied for command execution."
    except DoSomethingElseError:
        raise

    # Validate timeout parameters
    if timeout is not None and timeout <= 0:
        return "Error: Timeout must be a positive number of seconds."

    if timeout_action not in ["interrupt", "kill", "terminate"]:
        return "Error: timeout_action must be one of: 'interrupt', 'kill', 'terminate'."

    # Execute command with timeout support
    session_manager = get_session_manager()
    success, message = session_manager.execute_command(
        session_name,
        command,
        timeout=timeout,
        timeout_action=timeout_action,
        refresh_env=refresh_env,
    )

    if not success:
        return message

    # Capture output if requested
    if capture_output:
        # Give command a moment to execute (shorter if we have timeout info)
        import time

        if timeout is not None and timeout < 2:
            time.sleep(0.2)  # Shorter wait for quick timeouts
        else:
            time.sleep(0.5)

        output_success, output = session_manager.capture_session_output(session_name)
        if output_success:
            return f"{message}\n\nRecent output:\n{output}"
        else:
            return f"{message}\n\nWarning: Could not capture output: {output}"

    return message


@tool
def tmux_get_output(context: "AgentContext", session_name: str, lines: int = 50) -> str:
    """Get recent output from a tmux session.

    Retrieves and formats recent output from the specified session.
    This includes both stdout and stderr output with timestamps.

    Args:
        session_name: Name of the target session
        lines: Number of recent lines to retrieve (default: 50)
    """
    # Check if tmux is available
    if not _check_tmux_available():
        return "Error: tmux is not available on this system."

    # Validate lines parameter
    if lines is None:
        lines = 50
    if lines < 0:
        lines = 50
    elif lines > 1000:
        lines = 1000  # Cap at reasonable limit

    session_manager = get_session_manager()
    success, output = session_manager.capture_session_output(session_name, lines)

    if not success:
        return f"Error: {output}"

    return f"## Output from session '{session_name}'\n\n```\n{output}\n```"


@tool
def tmux_set_session_timeout(
    context: "AgentContext", session_name: str, timeout: Optional[int] = None
) -> str:
    """Set the default timeout for all commands in a tmux session.

    Configures a default timeout that will be used for all commands executed
    in the specified session, unless overridden by command-specific timeouts.

    Args:
        session_name: Name of the target session
        timeout: Default timeout in seconds (None to disable default timeout)
    """
    # Check if tmux is available
    if not _check_tmux_available():
        return "Error: tmux is not available on this system."

    # Validate timeout parameter
    if timeout is not None and timeout <= 0:
        return "Error: Timeout must be a positive number of seconds."

    session_manager = get_session_manager()
    success, message = session_manager.set_session_timeout(session_name, timeout)

    return message


@tool
def tmux_destroy_session(context: "AgentContext", session_name: str) -> str:
    """Destroy a specific tmux session.

    Terminates a tmux session and cleans up associated resources.
    All processes running in the session will be terminated.

    Args:
        session_name: Name of the session to destroy
    """
    # Check if tmux is available
    if not _check_tmux_available():
        return "Error: tmux is not available on this system."

    # Check permissions
    try:
        if not context.sandbox.check_permissions("tmux_destroy_session", session_name):
            return "Error: Permission denied for session destruction."
    except DoSomethingElseError:
        raise

    session_manager = get_session_manager()
    success, message = session_manager.destroy_session(session_name)

    return message


@tool
def tmux_update_session_environment(context: "AgentContext", session_name: str) -> str:
    """Update environment variables for an existing tmux session.

    Refreshes SSH agent sockets and other environment variables that may
    change over time. This is useful for maintaining SSH connectivity and
    other environment-dependent functionality in long-running sessions.

    Args:
        session_name: Name of the session to update
    """
    # Check if tmux is available
    if not _check_tmux_available():
        return "Error: tmux is not available on this system."

    session_manager = get_session_manager()
    success, message = session_manager.update_session_environment(session_name)

    return message


@tool
def tmux_destroy_all_sessions(context: "AgentContext") -> str:
    """Destroy all managed tmux sessions.

    Terminates all tmux sessions created by this tool and cleans up
    associated resources. This is useful for cleanup or resetting
    the session environment.

    Warning: This will terminate all background processes in all sessions.
    """
    # Check if tmux is available
    if not _check_tmux_available():
        return "Error: tmux is not available on this system."

    # Check permissions
    try:
        if not context.sandbox.check_permissions("tmux_destroy_all_sessions", "all"):
            return "Error: Permission denied for mass session destruction."
    except DoSomethingElseError:
        raise

    session_manager = get_session_manager()
    sessions = session_manager.list_sessions()

    if not sessions:
        return "No sessions to destroy."

    # Destroy all sessions
    destroyed_count = 0
    errors = []

    for session in sessions:
        success, message = session_manager.destroy_session(session["name"])
        if success:
            destroyed_count += 1
        else:
            errors.append(f"Failed to destroy {session['name']}: {message}")

    result = f"Destroyed {destroyed_count} sessions."
    if errors:
        result += "\n\nErrors:\n" + "\n".join(errors)

    return result


# List of all tmux tools for export
TMUX_TOOLS = [
    tmux_create_session,
    tmux_list_sessions,
    tmux_execute_command,
    tmux_get_output,
    tmux_set_session_timeout,
    tmux_update_session_environment,
    tmux_destroy_session,
    tmux_destroy_all_sessions,
]
