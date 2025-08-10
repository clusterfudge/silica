"""
Tmux session management classes for the TmuxTool.

This module provides the core session management functionality for persistent
shell sessions using tmux.
"""

import subprocess
import time
import uuid
import signal
import os
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import atexit
import re
import shlex


class TmuxSession:
    """Represents a single tmux session with output buffering and state tracking."""

    def __init__(
        self,
        name: str,
        tmux_session_name: str,
        max_buffer_size: int = 1000,
        default_timeout: Optional[int] = None,
    ):
        self.name = name
        self.tmux_session_name = tmux_session_name
        self.created_at = datetime.now()
        self.last_activity = self.created_at
        self.commands_executed = []
        self.status = "active"  # active, inactive, error
        self.max_buffer_size = max_buffer_size
        self.default_timeout = (
            default_timeout  # Default timeout for commands in this session
        )

        # Output buffering with circular buffer
        self.output_buffer = deque(maxlen=max_buffer_size)
        self.error_buffer = deque(maxlen=max_buffer_size)

        # Threading for output capture
        self._output_thread = None
        self._stop_output_capture = False

    def add_command(self, command: str, timeout: Optional[int] = None):
        """Record a command execution."""
        self.commands_executed.append(
            {
                "command": command,
                "timestamp": datetime.now(),
                "timeout": timeout,
            }
        )
        self.last_activity = datetime.now()

    def add_output(self, output: str, is_error: bool = False):
        """Add output to the appropriate buffer."""
        timestamp = datetime.now()
        buffer = self.error_buffer if is_error else self.output_buffer

        # Split output into lines and add each with timestamp
        for line in output.splitlines():
            buffer.append(
                {
                    "timestamp": timestamp,
                    "content": line,
                }
            )

        self.last_activity = timestamp

    def get_recent_output(self, lines: int = 50, include_errors: bool = True) -> str:
        """Get recent output from the session."""
        result = []

        # Combine and sort output by timestamp
        all_output = []

        # Add regular output
        for entry in self.output_buffer:
            all_output.append(("stdout", entry))

        # Add error output if requested
        if include_errors:
            for entry in self.error_buffer:
                all_output.append(("stderr", entry))

        # Sort by timestamp
        all_output.sort(key=lambda x: x[1]["timestamp"])

        # Take the most recent entries
        recent_output = all_output[-lines:] if lines > 0 else all_output

        # Format output
        for output_type, entry in recent_output:
            timestamp_str = entry["timestamp"].strftime("%H:%M:%S")
            prefix = "[ERR]" if output_type == "stderr" else "[OUT]"
            result.append(f"{timestamp_str} {prefix} {entry['content']}")

        return "\n".join(result) if result else "No output available"

    def get_session_info(self) -> Dict:
        """Get session information for display."""
        return {
            "name": self.name,
            "tmux_session_name": self.tmux_session_name,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "commands_executed": len(self.commands_executed),
            "output_lines": len(self.output_buffer),
            "error_lines": len(self.error_buffer),
        }


class TmuxSessionManager:
    """Manages multiple tmux sessions with cleanup and monitoring."""

    def __init__(
        self,
        session_prefix: str = "hdev",
        max_sessions: int = 10,
        global_default_timeout: Optional[int] = None,
    ):
        self.session_prefix = session_prefix
        self.max_sessions = max_sessions
        self.sessions: Dict[str, TmuxSession] = {}
        self.cleanup_registered = False
        self.global_default_timeout = global_default_timeout  # Global default timeout

        # Register cleanup handler
        if not self.cleanup_registered:
            atexit.register(self.cleanup_all_sessions)
            self.cleanup_registered = True

    def _generate_tmux_session_name(self, user_name: str) -> str:
        """Generate a unique tmux session name."""
        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())[:8]
        return f"{self.session_prefix}_{user_name}_{timestamp}_{unique_id}"

    def _validate_session_name(self, name: str) -> bool:
        """Validate session name contains only allowed characters."""
        return bool(re.match(r"^[a-zA-Z0-9_-]+$", name))

    def _get_environment_variables_for_tmux(self) -> Dict[str, Optional[str]]:
        """Get environment variables that should be passed to tmux sessions.

        Returns:
            Dictionary of environment variable names to values
        """
        # SSH agent and authentication related variables
        ssh_env_vars = {
            "SSH_AUTH_SOCK": os.getenv("SSH_AUTH_SOCK"),
            "SSH_AGENT_PID": os.getenv("SSH_AGENT_PID"),
            "SSH_CONNECTION": os.getenv("SSH_CONNECTION"),
        }

        # Display and terminal related variables
        display_env_vars = {
            "DISPLAY": os.getenv("DISPLAY"),
            "TERM": os.getenv("TERM"),
            "COLORTERM": os.getenv("COLORTERM"),
        }

        # Development environment variables
        dev_env_vars = {
            "LANG": os.getenv("LANG"),
            "LC_ALL": os.getenv("LC_ALL"),
            "PATH": os.getenv("PATH"),  # Ensure PATH is preserved
        }

        # Combine all environment variables
        all_env_vars = {**ssh_env_vars, **display_env_vars, **dev_env_vars}

        # Filter out None values and return
        return {k: v for k, v in all_env_vars.items() if v is not None}

    def _run_tmux_command(self, command: List[str]) -> Tuple[int, str, str]:
        """Run a tmux command and return exit code, stdout, stderr."""
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except Exception as e:
            return -1, "", str(e)

    def create_session(
        self, session_name: str, initial_command: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Create a new tmux session."""
        if not self._validate_session_name(session_name):
            return (
                False,
                "Invalid session name. Use only alphanumeric characters, underscores, and hyphens.",
            )

        if session_name in self.sessions:
            return False, f"Session '{session_name}' already exists."

        if len(self.sessions) >= self.max_sessions:
            return False, f"Maximum number of sessions ({self.max_sessions}) reached."

        # Generate unique tmux session name
        tmux_session_name = self._generate_tmux_session_name(session_name)

        # Get current working directory to inherit from parent process
        current_cwd = os.getcwd()

        # Create tmux session with SSH agent environment variables and working directory
        command = [
            "tmux",
            "new-session",
            "-d",
            "-s",
            tmux_session_name,
            "-c",
            current_cwd,
        ]

        # Add SSH and other important environment variables
        env_vars = self._get_environment_variables_for_tmux()
        for key, value in env_vars.items():
            if value is not None:
                command.extend(["-e", f"{key}={value}"])

        exit_code, stdout, stderr = self._run_tmux_command(command)

        if exit_code != 0:
            return False, f"Failed to create tmux session: {stderr}"

        # Create session object
        session = TmuxSession(session_name, tmux_session_name)
        self.sessions[session_name] = session

        # Execute initial command if provided
        if initial_command:
            session.add_command(initial_command)
            self._send_command_to_session(tmux_session_name, initial_command)

        return True, f"Session '{session_name}' created successfully."

    def update_session_environment(self, session_name: str) -> Tuple[bool, str]:
        """Update environment variables for an existing tmux session.

        This is useful for refreshing SSH agent sockets and other environment
        variables that may change over time.

        Args:
            session_name: Name of the session to update

        Returns:
            Tuple of (success, message)
        """
        if session_name not in self.sessions:
            return False, f"Session '{session_name}' not found."

        session = self.sessions[session_name]
        env_vars = self._get_environment_variables_for_tmux()

        updated_vars = []
        failed_vars = []

        for key, value in env_vars.items():
            if value is not None:
                exit_code, stdout, stderr = self._run_tmux_command(
                    ["tmux", "setenv", "-t", session.tmux_session_name, key, value]
                )

                if exit_code == 0:
                    updated_vars.append(key)
                else:
                    failed_vars.append(f"{key}: {stderr}")

        if failed_vars:
            return False, f"Failed to update some variables: {', '.join(failed_vars)}"
        elif updated_vars:
            return True, f"Updated environment variables: {', '.join(updated_vars)}"
        else:
            return True, "No environment variables to update"

    def destroy_session(self, session_name: str) -> Tuple[bool, str]:
        """Destroy a tmux session."""
        if session_name not in self.sessions:
            return False, f"Session '{session_name}' not found."

        session = self.sessions[session_name]

        # Kill the tmux session
        exit_code, stdout, stderr = self._run_tmux_command(
            ["tmux", "kill-session", "-t", session.tmux_session_name]
        )

        # Remove from our tracking (even if tmux command failed)
        del self.sessions[session_name]

        if exit_code != 0:
            return (
                True,
                f"Session '{session_name}' removed (tmux cleanup may have failed: {stderr})",
            )

        return True, f"Session '{session_name}' destroyed successfully."

    def list_sessions(self) -> List[Dict]:
        """List all active sessions."""
        # Update session statuses by checking tmux
        self._update_session_statuses()

        return [session.get_session_info() for session in self.sessions.values()]

    def get_session(self, session_name: str) -> Optional[TmuxSession]:
        """Get a specific session by name."""
        return self.sessions.get(session_name)

    def execute_command(
        self,
        session_name: str,
        command: str,
        timeout: Optional[int] = None,
        timeout_action: str = "interrupt",
        refresh_env: bool = False,
    ) -> Tuple[bool, str]:
        """Execute a command in a specific session with optional timeout."""
        if session_name not in self.sessions:
            return False, f"Session '{session_name}' not found."

        session = self.sessions[session_name]

        # Optionally refresh environment variables before command execution
        if refresh_env:
            env_success, env_message = self.update_session_environment(session_name)
            if not env_success:
                return False, f"Failed to refresh environment: {env_message}"

        # Determine effective timeout
        effective_timeout = self._determine_effective_timeout(session_name, timeout)

        # Send command to tmux session with timeout support
        if effective_timeout is not None:
            success, message = self._execute_command_with_timeout(
                session.tmux_session_name, command, effective_timeout, timeout_action
            )
        else:
            success, message = self._send_command_to_session_without_timeout(
                session.tmux_session_name, command
            )

        if success:
            session.add_command(command, effective_timeout)
            if effective_timeout is not None:
                env_note = " (env refreshed)" if refresh_env else ""
                return (
                    True,
                    f"Command executed in session '{session_name}' (timeout: {effective_timeout}s){env_note}",
                )
            else:
                env_note = " (env refreshed)" if refresh_env else ""
                return True, f"Command executed in session '{session_name}'{env_note}"
        else:
            return False, message

    def _validate_and_sanitize_command(self, command: str) -> Tuple[bool, str]:
        """Validate and sanitize a command for safe shell execution.

        Returns:
            Tuple of (is_valid, sanitized_command_or_error_message)
        """
        # Check for unbalanced quotes
        if not self._check_quote_balance(command):
            return False, f"Command has unbalanced quotes: {command}"

        # For commands with quotes, use a safer execution method
        if self._has_complex_quotes(command):
            return True, self._sanitize_complex_command(command)

        return True, command

    def _check_quote_balance(self, command: str) -> bool:
        """Check if quotes are properly balanced in a command."""
        try:
            # Use shlex to parse and validate quote balance
            shlex.split(command)
            return True
        except ValueError:
            # shlex.split raises ValueError for unbalanced quotes
            # However, some valid shell constructs like 'It\'s' fail shlex
            # So let's do a simpler manual check for our use case
            return self._manual_quote_check(command)

    def _manual_quote_check(self, command: str) -> bool:
        """Manual quote balance check for edge cases."""
        single_quotes = 0
        double_quotes = 0
        i = 0

        while i < len(command):
            char = command[i]

            if char == "'" and (i == 0 or command[i - 1] != "\\"):
                single_quotes += 1
            elif char == '"' and (i == 0 or command[i - 1] != "\\"):
                double_quotes += 1

            i += 1

        # For our purposes, we consider quotes balanced if they appear in pairs
        # or if we have shell-style quote structures
        return single_quotes % 2 == 0 and double_quotes % 2 == 0

    def _has_complex_quotes(self, command: str) -> bool:
        """Check if command has complex quote usage that needs special handling."""
        # Check for escaped quotes within quotes
        if re.search(
            r"'[^']*\\'[^']*'", command
        ):  # Single quotes with escaped single quotes
            return True
        if re.search(
            r'"[^"]*\\"[^"]*"', command
        ):  # Double quotes with escaped double quotes
            return True
        if "\n" in command:  # Multi-line commands
            return True
        return False

    def _sanitize_complex_command(self, command: str) -> str:
        """Sanitize complex commands with quotes for safe execution."""
        # For single quotes with escaped single quotes, convert to double quotes
        if re.search(r"'[^']*\\'[^']*'", command):
            # Convert echo 'It\'s working' to echo "It's working"
            # This is a more precise regex replacement
            def replace_escaped_single_quotes(match):
                content = match.group(1) + "'" + match.group(2)
                return f'"{content}"'

            command = re.sub(
                r"'([^']*)\\'([^']*)'", replace_escaped_single_quotes, command
            )

        # For multi-line strings, ensure proper escaping
        if "\n" in command:
            # Replace literal newlines with proper shell escaping
            command = command.replace("\n", "\\n")

        return command

    def _detect_shell_stuck_state(self, output: str) -> Optional[str]:
        """Detect if shell is stuck in an incomplete state.

        Returns:
            The stuck state type if detected (e.g., 'quote>', 'dquote>'), None otherwise
        """
        lines = output.strip().split("\n")
        if not lines:
            return None

        # Check the last line first (most recent state)
        last_line = lines[-1].strip()

        # Check for common stuck states in order of specificity
        stuck_states = [
            "dquote>",
            "quote>",
            "heredoc>",
            "cmdsubst>",
            "for>",
            "while>",
            "if>",
        ]
        for state in stuck_states:
            if last_line.endswith(state):
                return state

        # If last line doesn't show stuck state, check previous lines
        if len(lines) > 1:
            for line in reversed(lines[-3:-1]):  # Check 2nd and 3rd to last lines
                line = line.strip()
                for state in stuck_states:
                    if line.endswith(state):
                        return state

        return None

    def _recover_from_stuck_state(
        self, tmux_session_name: str, stuck_state: str
    ) -> Tuple[bool, str]:
        """Attempt to recover from a stuck shell state.

        Args:
            tmux_session_name: Name of the tmux session
            stuck_state: The type of stuck state detected

        Returns:
            Tuple of (success, message)
        """
        recovery_commands = {
            "quote>": ["'", "Enter"],  # Close single quote
            "dquote>": ['"', "Enter"],  # Close double quote
            "heredoc>": ["EOF", "Enter"],  # Close heredoc
            "cmdsubst>": [")", "Enter"],  # Close command substitution
        }

        # For other states or as fallback, send Ctrl+C
        if stuck_state not in recovery_commands:
            recovery_commands[stuck_state] = ["C-c"]

        commands = recovery_commands[stuck_state]

        for cmd in commands:
            exit_code, stdout, stderr = self._run_tmux_command(
                ["tmux", "send-keys", "-t", tmux_session_name, cmd]
            )
            if exit_code != 0:
                return False, f"Failed to send recovery command '{cmd}': {stderr}"

        # Give a moment for the recovery to take effect
        time.sleep(0.2)

        return True, f"Attempted recovery from {stuck_state} state"

    def set_session_timeout(
        self, session_name: str, timeout: Optional[int]
    ) -> Tuple[bool, str]:
        """Set default timeout for a session.

        Args:
            session_name: Name of the session
            timeout: Default timeout in seconds (None to disable)

        Returns:
            Tuple of (success, message)
        """
        if session_name not in self.sessions:
            return False, f"Session '{session_name}' not found."

        self.sessions[session_name].default_timeout = timeout
        if timeout is None:
            return True, f"Disabled default timeout for session '{session_name}'"
        else:
            return (
                True,
                f"Set default timeout for session '{session_name}' to {timeout} seconds",
            )

    def _determine_effective_timeout(
        self, session_name: str, command_timeout: Optional[int]
    ) -> Optional[int]:
        """Determine the effective timeout for a command.

        Priority: command_timeout > session_timeout > global_timeout
        """
        if command_timeout is not None:
            return command_timeout

        if session_name in self.sessions:
            session_timeout = self.sessions[session_name].default_timeout
            if session_timeout is not None:
                return session_timeout

        return self.global_default_timeout

    def _execute_command_with_timeout(
        self,
        tmux_session_name: str,
        command: str,
        timeout: Optional[int] = None,
        timeout_action: str = "interrupt",
    ) -> Tuple[bool, str]:
        """Execute a command with timeout support.

        Args:
            tmux_session_name: Tmux session name
            command: Command to execute
            timeout: Timeout in seconds (None for no timeout)
            timeout_action: Action to take on timeout ('interrupt', 'kill', 'terminate')

        Returns:
            Tuple of (success, message)
        """
        if timeout is None:
            # No timeout, use the original method
            return self._send_command_to_session_without_timeout(
                tmux_session_name, command
            )

        # Send the command
        exit_code, stdout, stderr = self._run_tmux_command(
            ["tmux", "send-keys", "-t", tmux_session_name, command, "Enter"]
        )

        if exit_code != 0:
            return False, f"Failed to send command: {stderr}"

        # Wait for command completion or timeout
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check shell state
            capture_exit_code, capture_output, capture_stderr = self._run_tmux_command(
                ["tmux", "capture-pane", "-t", tmux_session_name, "-p"]
            )

            if capture_exit_code == 0:
                # Check if we're back to a normal prompt (command finished)
                if self._is_command_complete(capture_output):
                    stuck_state = self._detect_shell_stuck_state(capture_output)
                    if stuck_state:
                        # Attempt recovery
                        recovery_success, recovery_msg = self._recover_from_stuck_state(
                            tmux_session_name, stuck_state
                        )
                        if recovery_success:
                            return (
                                True,
                                f"Command completed (recovered from {stuck_state})",
                            )
                        else:
                            return (
                                False,
                                f"Command completed but shell stuck in {stuck_state}. Recovery failed: {recovery_msg}",
                            )

                    return True, "Command completed successfully"

            # Brief sleep before next check
            time.sleep(0.2)

        # Timeout occurred - take action
        success, message = self._handle_command_timeout(
            tmux_session_name, timeout_action, timeout
        )
        return success, f"Command timed out after {timeout}s. {message}"

    def _is_command_complete(self, output: str) -> bool:
        """Check if command execution is complete by looking for a normal prompt.

        Args:
            output: Captured tmux pane output

        Returns:
            True if command appears to be complete
        """
        lines = output.strip().split("\n")
        if not lines:
            return False

        last_line = lines[-1].strip()

        # First check if we're in a stuck state - this takes precedence
        stuck_states = [
            "quote>",
            "dquote>",
            "heredoc>",
            "cmdsubst>",
            "for>",
            "while>",
            "if>",
        ]
        for state in stuck_states:
            if last_line.endswith(state):
                return False

        # Look for common shell prompts that indicate readiness
        # But exclude the stuck state prompts we just checked
        prompt_indicators = ["❯", "$", "#", "%"]

        # Check if last line ends with a prompt indicator
        for indicator in prompt_indicators:
            if last_line.endswith(indicator):
                return True

        # Special case for '>' - only consider it a prompt if it's not a stuck state
        if last_line.endswith(">") and not any(
            last_line.endswith(state) for state in stuck_states
        ):
            return True

        # If last line is empty or contains only spaces, check previous line
        if not last_line and len(lines) > 1:
            prev_line = lines[-2].strip()
            # Apply same logic to previous line
            for state in stuck_states:
                if prev_line.endswith(state):
                    return False
            for indicator in prompt_indicators:
                if prev_line.endswith(indicator):
                    return True
            if prev_line.endswith(">") and not any(
                prev_line.endswith(state) for state in stuck_states
            ):
                return True

        return False

    def _handle_command_timeout(
        self, tmux_session_name: str, timeout_action: str, timeout: int
    ) -> Tuple[bool, str]:
        """Handle command timeout by taking the specified action.

        Args:
            tmux_session_name: Tmux session name
            timeout_action: Action to take ('interrupt', 'kill', 'terminate')
            timeout: The timeout value that was exceeded

        Returns:
            Tuple of (success, message)
        """
        if timeout_action == "interrupt":
            # Send Ctrl+C to interrupt the command
            exit_code, stdout, stderr = self._run_tmux_command(
                ["tmux", "send-keys", "-t", tmux_session_name, "C-c"]
            )
            if exit_code == 0:
                return True, "Sent interrupt signal (Ctrl+C)"
            else:
                return False, f"Failed to send interrupt: {stderr}"

        elif timeout_action == "kill":
            # Send SIGKILL to the session's processes
            return self._kill_session_processes(tmux_session_name)

        elif timeout_action == "terminate":
            # Terminate the entire session
            if tmux_session_name in [
                s.tmux_session_name for s in self.sessions.values()
            ]:
                session_name = next(
                    name
                    for name, s in self.sessions.items()
                    if s.tmux_session_name == tmux_session_name
                )
                success, message = self.destroy_session(session_name)
                return success, f"Terminated session: {message}"
            else:
                return False, "Session not found for termination"
        else:
            return False, f"Unknown timeout action: {timeout_action}"

    def _kill_session_processes(self, tmux_session_name: str) -> Tuple[bool, str]:
        """Kill processes running in a tmux session.

        Args:
            tmux_session_name: Tmux session name

        Returns:
            Tuple of (success, message)
        """
        try:
            # Get the session's PID and kill processes
            exit_code, stdout, stderr = self._run_tmux_command(
                [
                    "tmux",
                    "display-message",
                    "-t",
                    tmux_session_name,
                    "-p",
                    "#{pane_pid}",
                ]
            )

            if exit_code == 0 and stdout.strip():
                pane_pid = int(stdout.strip())

                # Kill the pane's process group
                import os

                try:
                    os.killpg(os.getpgid(pane_pid), signal.SIGTERM)
                    time.sleep(0.5)  # Give processes time to terminate gracefully

                    # If still running, force kill
                    try:
                        os.killpg(os.getpgid(pane_pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # Process already terminated

                    return True, f"Killed processes in session (PID: {pane_pid})"
                except ProcessLookupError:
                    return True, "Process already terminated"
                except PermissionError:
                    return False, "Permission denied when killing processes"
            else:
                return False, f"Could not get session PID: {stderr}"

        except Exception as e:
            return False, f"Error killing processes: {str(e)}"

    def _send_command_to_session_without_timeout(
        self, tmux_session_name: str, command: str
    ) -> Tuple[bool, str]:
        """Send a command to a tmux session without timeout (original implementation)."""
        # Validate and sanitize the command
        is_valid, sanitized_command = self._validate_and_sanitize_command(command)
        if not is_valid:
            return False, sanitized_command  # sanitized_command contains error message

        # Send the sanitized command
        exit_code, stdout, stderr = self._run_tmux_command(
            ["tmux", "send-keys", "-t", tmux_session_name, sanitized_command, "Enter"]
        )

        if exit_code != 0:
            return False, f"Failed to send command: {stderr}"

        # Check for stuck shell state after command execution
        time.sleep(0.1)  # Brief pause to let command execute

        # Capture current shell state
        capture_exit_code, capture_output, capture_stderr = self._run_tmux_command(
            ["tmux", "capture-pane", "-t", tmux_session_name, "-p"]
        )

        if capture_exit_code == 0:
            stuck_state = self._detect_shell_stuck_state(capture_output)
            if stuck_state:
                # Attempt recovery
                recovery_success, recovery_msg = self._recover_from_stuck_state(
                    tmux_session_name, stuck_state
                )
                if recovery_success:
                    return (
                        True,
                        f"Command sent successfully (recovered from {stuck_state})",
                    )
                else:
                    return (
                        False,
                        f"Command sent but shell stuck in {stuck_state}. Recovery failed: {recovery_msg}",
                    )

        return True, "Command sent successfully"

    def _send_command_to_session(
        self, tmux_session_name: str, command: str
    ) -> Tuple[bool, str]:
        """Send a command to a tmux session with quote handling and recovery."""
        # Validate and sanitize the command
        is_valid, sanitized_command = self._validate_and_sanitize_command(command)
        if not is_valid:
            return False, sanitized_command  # sanitized_command contains error message

        # Send the sanitized command
        exit_code, stdout, stderr = self._run_tmux_command(
            ["tmux", "send-keys", "-t", tmux_session_name, sanitized_command, "Enter"]
        )

        if exit_code != 0:
            return False, f"Failed to send command: {stderr}"

        # Check for stuck shell state after command execution
        time.sleep(0.1)  # Brief pause to let command execute

        # Capture current shell state
        capture_exit_code, capture_output, capture_stderr = self._run_tmux_command(
            ["tmux", "capture-pane", "-t", tmux_session_name, "-p"]
        )

        if capture_exit_code == 0:
            stuck_state = self._detect_shell_stuck_state(capture_output)
            if stuck_state:
                # Attempt recovery
                recovery_success, recovery_msg = self._recover_from_stuck_state(
                    tmux_session_name, stuck_state
                )
                if recovery_success:
                    return (
                        True,
                        f"Command sent successfully (recovered from {stuck_state})",
                    )
                else:
                    return (
                        False,
                        f"Command sent but shell stuck in {stuck_state}. Recovery failed: {recovery_msg}",
                    )

        return True, "Command sent successfully"

    def capture_session_output(
        self, session_name: str, lines: int = 50
    ) -> Tuple[bool, str]:
        """Capture recent output from a session."""
        if session_name not in self.sessions:
            return False, f"Session '{session_name}' not found."

        session = self.sessions[session_name]

        # Capture output from tmux
        exit_code, stdout, stderr = self._run_tmux_command(
            ["tmux", "capture-pane", "-t", session.tmux_session_name, "-p"]
        )

        if exit_code != 0:
            return False, f"Failed to capture output: {stderr}"

        # Update session output buffer
        if stdout:
            session.add_output(stdout)

        # Return recent output
        return True, session.get_recent_output(lines)

    def _update_session_statuses(self):
        """Update session statuses by checking tmux."""
        # Get list of active tmux sessions
        exit_code, stdout, stderr = self._run_tmux_command(["tmux", "list-sessions"])

        if exit_code != 0:
            # If tmux command fails, mark all sessions as inactive
            for session in self.sessions.values():
                session.status = "inactive"
            return

        # Parse tmux session list
        active_sessions = set()
        for line in stdout.splitlines():
            if ":" in line:
                session_name = line.split(":")[0]
                active_sessions.add(session_name)

        # Update session statuses
        for session in self.sessions.values():
            if session.tmux_session_name in active_sessions:
                session.status = "active"
            else:
                session.status = "inactive"

    def cleanup_all_sessions(self):
        """Clean up all managed sessions."""
        for session_name in list(self.sessions.keys()):
            try:
                self.destroy_session(session_name)
            except Exception as e:
                print(f"Error cleaning up session {session_name}: {e}")


# Global session manager instance
_session_manager = None


def get_session_manager() -> TmuxSessionManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = TmuxSessionManager()
    return _session_manager
