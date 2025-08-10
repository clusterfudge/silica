"""
Shell tools providing dual architecture for command execution.

This module provides two complementary approaches for shell operations:
1. shell_execute - Quick command execution with unlimited output capture
2. shell_session_* - Persistent session management for complex workflows
"""

import asyncio
import io
import re
import subprocess
import threading
import time
from queue import Empty, Queue
from typing import Optional

from silica.developer.context import AgentContext
from silica.developer.sandbox import DoSomethingElseError

from .framework import tool


@tool
async def shell_execute(
    context: "AgentContext", command: str, timeout: Optional[int] = None
):
    """Execute a shell command quickly with unlimited output capture.

    Best for:
    - File operations (cat, ls, grep, etc.)
    - System queries (df, ps, netstat, etc.)
    - Quick builds or tests
    - Any command with large output

    Features:
    - Unlimited output capture (no buffer constraints)
    - No session overhead
    - Direct process execution
    - Enhanced timeout handling
    - Live output streaming
    - Interactive user prompts for long-running commands

    Args:
        command: The shell command to execute
        timeout: Optional timeout in seconds (default: 30)
    """
    try:
        # Check for potentially dangerous commands
        dangerous_commands = [
            r"\bsudo\b",
        ]

        if any(re.search(cmd, command) for cmd in dangerous_commands):
            return "Error: This command is not allowed for safety reasons."

        try:
            if not context.sandbox.check_permissions("shell", command):
                return "Error: Operator denied permission."
        except DoSomethingElseError:
            raise  # Re-raise to be handled by higher-level components

        return await _run_shell_command_with_interactive_timeout(
            context, command, timeout or 30
        )

    except Exception as e:
        return f"Error executing command: {str(e)}"


async def _run_shell_command_with_interactive_timeout(
    context: "AgentContext", command: str, initial_timeout: int = 30, live=None
):
    """Run a shell command with interactive timeout handling.

    Args:
        context: The agent context
        command: The shell command to execute
        initial_timeout: Initial timeout in seconds before prompting user
        live: Optional Rich Live instance for real-time output streaming
    """
    # Start the process
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,  # Prevent stdin capture conflicts with CLI
        text=True,
        bufsize=0,  # Unbuffered for real-time output
    )

    # Queues to collect output from threads
    stdout_queue = Queue()
    stderr_queue = Queue()

    def read_output(pipe, queue):
        """Thread function to read from pipe and put in queue."""
        try:
            while True:
                line = pipe.readline()
                if not line:
                    break
                queue.put(line)
        except Exception as e:
            queue.put(f"Error reading output: {str(e)}\n")
        finally:
            pipe.close()

    # Start threads to read stdout and stderr
    stdout_thread = threading.Thread(
        target=read_output, args=(process.stdout, stdout_queue)
    )
    stderr_thread = threading.Thread(
        target=read_output, args=(process.stderr, stderr_queue)
    )
    stdout_thread.daemon = True
    stderr_thread.daemon = True
    stdout_thread.start()
    stderr_thread.start()

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    start_time = time.time()
    current_timeout = initial_timeout

    while True:
        # Check if process has completed
        returncode = process.poll()
        if returncode is not None:
            # Process completed, collect remaining output
            _collect_remaining_output(
                stdout_queue, stderr_queue, stdout_buffer, stderr_buffer
            )

            # Wait for threads to finish
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)

            # Prepare final output
            output = f"Exit code: {returncode}\n"
            stdout_content = stdout_buffer.getvalue()
            stderr_content = stderr_buffer.getvalue()

            if stdout_content:
                output += f"STDOUT:\n{stdout_content}\n"
            if stderr_content:
                output += f"STDERR:\n{stderr_content}\n"

            return output

        # Collect any new output
        _collect_output_batch(stdout_queue, stderr_queue, stdout_buffer, stderr_buffer)

        # If we have live streaming, update the display with current output
        if live:
            current_stdout = stdout_buffer.getvalue()
            current_stderr = stderr_buffer.getvalue()

            if current_stdout or current_stderr:
                from rich.console import Group
                from rich.text import Text

                output_parts = []
                if current_stdout:
                    output_parts.extend(
                        [Text("STDOUT:", style="bold green"), Text(current_stdout)]
                    )
                if current_stderr:
                    if output_parts:
                        output_parts.append(Text(""))  # Empty line separator
                    output_parts.extend(
                        [Text("STDERR:", style="bold red"), Text(current_stderr)]
                    )

                live_content = Group(*output_parts)
                live.update(live_content)

        # Check if we've exceeded the timeout
        elapsed = time.time() - start_time
        if elapsed >= current_timeout:
            # Show current output to user
            current_stdout = stdout_buffer.getvalue()
            current_stderr = stderr_buffer.getvalue()

            status_msg = f"Command has been running for {elapsed:.1f} seconds.\n"
            if current_stdout:
                status_msg += (
                    f"Current STDOUT:\n{current_stdout[-500:]}...\n"
                    if len(current_stdout) > 500
                    else f"Current STDOUT:\n{current_stdout}\n"
                )
            if current_stderr:
                status_msg += (
                    f"Current STDERR:\n{current_stderr[-500:]}...\n"
                    if len(current_stderr) > 500
                    else f"Current STDERR:\n{current_stderr}\n"
                )

            # Display status message - use live if available, otherwise normal system message
            if live:
                from rich.console import Group
                from rich.text import Text

                # Create a combined display with current output and status
                display_parts = []

                # Add current output
                current_stdout = stdout_buffer.getvalue()
                current_stderr = stderr_buffer.getvalue()

                if current_stdout:
                    display_parts.extend(
                        [Text("STDOUT:", style="bold green"), Text(current_stdout)]
                    )
                if current_stderr:
                    if display_parts:
                        display_parts.append(Text(""))  # Empty line separator
                    display_parts.extend(
                        [Text("STDERR:", style="bold red"), Text(current_stderr)]
                    )

                # Add timeout status
                display_parts.extend(
                    [
                        Text(""),  # Empty line
                        Text(
                            f"Command has been running for {elapsed:.1f} seconds.",
                            style="bold yellow",
                        ),
                        Text("Waiting for user input...", style="yellow"),
                    ]
                )

                live_display = Group(*display_parts)
                live.update(live_display)
            else:
                context.user_interface.handle_system_message(status_msg, markdown=False)

            # Race between user input and process completion
            # Create tasks for both user input and process monitoring
            user_input_task = asyncio.create_task(
                context.user_interface.get_user_input(
                    "Command is still running. Choose action:\n"
                    f"  [C]ontinue waiting ({initial_timeout}s more)\n"
                    "  [K]ill the process\n"
                    "  [B]ackground (continue but return current output)\n"
                    "Choice (C/K/B): "
                )
            )

            async def monitor_process_completion():
                """Monitor for process completion during user input."""
                while process.poll() is None:
                    await asyncio.sleep(0.1)
                return "PROCESS_COMPLETED"

            process_monitor_task = asyncio.create_task(monitor_process_completion())

            try:
                # Wait for whichever completes first
                done, pending = await asyncio.wait(
                    [user_input_task, process_monitor_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                # Check which task completed first
                completed_task = done.pop()
                if completed_task == process_monitor_task:
                    # Process completed while waiting for user input
                    # Continue to the process completion handling at top of loop
                    continue
                else:
                    # User input completed first
                    choice = completed_task.result().strip().upper()

            except asyncio.CancelledError:
                # Clean up if this whole function gets cancelled
                user_input_task.cancel()
                process_monitor_task.cancel()
                raise

            if choice == "K":
                # Kill the process
                try:
                    process.terminate()
                    # Give it a moment to terminate gracefully
                    await asyncio.sleep(1)
                    if process.poll() is None:
                        process.kill()

                    # Collect any final output
                    _collect_remaining_output(
                        stdout_queue, stderr_queue, stdout_buffer, stderr_buffer
                    )

                    output = "Command was killed by user.\n"
                    output += f"Execution time: {elapsed:.1f} seconds\n"

                    stdout_content = stdout_buffer.getvalue()
                    stderr_content = stderr_buffer.getvalue()

                    if stdout_content:
                        output += f"STDOUT (before kill):\n{stdout_content}\n"
                    if stderr_content:
                        output += f"STDERR (before kill):\n{stderr_content}\n"

                    return output

                except Exception as e:
                    return f"Error killing process: {str(e)}"

            elif choice == "B":
                # Background the process - return current output
                output = f"Command backgrounded after {elapsed:.1f} seconds (PID: {process.pid}).\n"
                output += (
                    "Note: Process continues running but output capture has stopped.\n"
                )

                stdout_content = stdout_buffer.getvalue()
                stderr_content = stderr_buffer.getvalue()

                if stdout_content:
                    output += f"STDOUT (so far):\n{stdout_content}\n"
                if stderr_content:
                    output += f"STDERR (so far):\n{stderr_content}\n"

                return output

            else:  # Default to 'C' - continue
                current_timeout += initial_timeout  # Add the same interval again
                if live:
                    # Update live display to show we're continuing
                    from rich.console import Group
                    from rich.text import Text

                    display_parts = []

                    # Add current output
                    current_stdout = stdout_buffer.getvalue()
                    current_stderr = stderr_buffer.getvalue()

                    if current_stdout:
                        display_parts.extend(
                            [Text("STDOUT:", style="bold green"), Text(current_stdout)]
                        )
                    if current_stderr:
                        if display_parts:
                            display_parts.append(Text(""))  # Empty line separator
                        display_parts.extend(
                            [Text("STDERR:", style="bold red"), Text(current_stderr)]
                        )

                    # Add continuation status
                    display_parts.extend(
                        [
                            Text(""),  # Empty line
                            Text(
                                f"Continuing to wait for {initial_timeout} more seconds...",
                                style="bold cyan",
                            ),
                        ]
                    )

                    live_display = Group(*display_parts)
                    live.update(live_display)
                else:
                    context.user_interface.handle_system_message(
                        f"Continuing to wait for {initial_timeout} more seconds...",
                        markdown=False,
                    )

        # Sleep briefly before next check
        await asyncio.sleep(0.5)


def _collect_output_batch(stdout_queue, stderr_queue, stdout_buffer, stderr_buffer):
    """Collect a batch of output from the queues."""
    # Collect stdout
    while True:
        try:
            line = stdout_queue.get_nowait()
            stdout_buffer.write(line)
        except Empty:
            break

    # Collect stderr
    while True:
        try:
            line = stderr_queue.get_nowait()
            stderr_buffer.write(line)
        except Empty:
            break


def _collect_remaining_output(stdout_queue, stderr_queue, stdout_buffer, stderr_buffer):
    """Collect any remaining output from the queues."""
    # Give threads a moment to finish
    time.sleep(0.1)

    # Collect any remaining output
    _collect_output_batch(stdout_queue, stderr_queue, stdout_buffer, stderr_buffer)


# Session-based shell tools (using tmux implementation)
# These will be imported from the existing tmux_tool module


@tool
async def shell_session_create(
    context: "AgentContext", session_name: str, initial_command: Optional[str] = None
):
    """Create a persistent shell session for complex workflows.

    Best for:
    - Background processes (web servers, builds, etc.)
    - Development environments with state
    - Multi-step workflows
    - Long-running tasks that need monitoring

    Features:
    - Session persistence across agent restarts
    - Background process management
    - State preservation (environment, working directory)
    - Session monitoring and coordination

    Args:
        session_name: Name for the session (alphanumeric, underscore, dash only)
        initial_command: Optional command to run immediately in the session
    """
    # Import tmux tool function
    from .tmux_tool import tmux_create_session

    return tmux_create_session(context, session_name, initial_command)


@tool
async def shell_session_execute(
    context: "AgentContext",
    session_name: str,
    command: str,
    timeout: Optional[int] = None,
    timeout_action: Optional[str] = None,
):
    """Execute a command in an existing shell session.

    Args:
        session_name: Name of the target session
        command: Command to execute
        timeout: Optional timeout in seconds
        timeout_action: Optional timeout action ('interrupt' or 'kill')
    """
    # Import tmux tool function
    from .tmux_tool import tmux_execute_command

    return tmux_execute_command(context, session_name, command, timeout, timeout_action)


@tool
def shell_session_list(context: "AgentContext"):
    """List all active shell sessions with their status and last activity.

    Returns formatted table of sessions with:
    - Session name
    - Status (active/inactive/error)
    - Created time
    - Last activity time
    - Command count
    """
    # Import tmux tool function
    from .tmux_tool import tmux_list_sessions

    return tmux_list_sessions(context)


@tool
def shell_session_get_output(
    context: "AgentContext", session_name: str, lines: Optional[int] = None
):
    """Get recent output from a shell session.

    Args:
        session_name: Name of the target session
        lines: Number of lines to retrieve (from end, default: 50)
    """
    # Import tmux tool function
    from .tmux_tool import tmux_get_output

    return tmux_get_output(context, session_name, lines or 50)


@tool
def shell_session_destroy(context: "AgentContext", session_name: str):
    """Destroy a specific shell session.

    Args:
        session_name: Name of the session to destroy
    """
    # Import tmux tool function
    from .tmux_tool import tmux_destroy_session

    return tmux_destroy_session(context, session_name)


@tool
def shell_session_set_timeout(context: "AgentContext", session_name: str, timeout: int):
    """Set the default timeout for a shell session.

    Args:
        session_name: Name of the session
        timeout: Default timeout in seconds for commands in this session
    """
    # Import tmux tool function
    from .tmux_tool import tmux_set_session_timeout

    return tmux_set_session_timeout(context, session_name, timeout)
