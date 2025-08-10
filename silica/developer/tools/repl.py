import subprocess
from queue import Empty

from silica.developer.context import AgentContext
from silica.developer.sandbox import DoSomethingElseError
from .framework import tool


def create_bash_live_display():
    """Create a Rich Live display for bash command output streaming.

    Returns:
        A context manager that provides live streaming for bash commands.

    Usage:
        with create_bash_live_display() as live_ctx:
            result = await live_ctx.run_command(context, "long_running_command")
    """
    from rich.live import Live
    from rich.text import Text

    class BashLiveContext:
        def __init__(self, live):
            self.live = live

        async def run_command(self, context, command, initial_timeout=30):
            """Run a command with live streaming using this context."""
            return await _run_bash_command_with_interactive_timeout(
                context, command, initial_timeout, live=self.live
            )

    class BashLiveDisplayManager:
        def __enter__(self):
            live_content = Text("Preparing to execute command...")
            self.live = Live(live_content, refresh_per_second=4)
            self.live.__enter__()
            return BashLiveContext(self.live)

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.live.__exit__(exc_type, exc_val, exc_tb)

    return BashLiveDisplayManager()


@tool
def python_repl(context: "AgentContext", code: str):
    """Run Python code in a sandboxed environment and return the output.
    This tool allows execution of Python code in a secure, isolated environment.

    For security reasons, the following limitations apply:
    1. No imports of potentially dangerous modules (os, sys, subprocess, etc.)
    2. No file operations (open, read, write)
    3. No use of eval, exec, or other dynamic code execution
    4. No use of __import__ or other import mechanisms

    Available modules and functions:
    - math, random, datetime, json, re
    - Basic built-ins like range, len, str, int, float, etc.
    - Collection operations: list, dict, set, tuple, sum, min, max, etc.
    - Other safe functions: all, any, enumerate, zip, sorted, reversed, etc.

    Example usage:
    ```python
    # Basic math operations
    result = 5 * 10
    print(f"5 * 10 = {result}")

    # Working with collections
    numbers = [1, 2, 3, 4, 5]
    print(f"Sum: {sum(numbers)}")
    print(f"Average: {sum(numbers)/len(numbers)}")

    # Using available modules
    import math
    print(f"Square root of 16: {math.sqrt(16)}")
    ```

    Args:
        code: The Python code to execute
    """
    import io
    import ast
    from contextlib import redirect_stdout, redirect_stderr

    # Security check - prevent potentially harmful operations
    try:
        parsed = ast.parse(code)
        for node in ast.walk(parsed):
            # Prevent imports that could be dangerous
            if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                for name in node.names:
                    module = name.name.split(".")[0]
                    dangerous_modules = [
                        "os",
                        "subprocess",
                        "sys",
                        "shutil",
                        "importlib",
                        "pickle",
                        "socket",
                        "ctypes",
                        "pty",
                        "posix",
                    ]
                    if module in dangerous_modules:
                        return f"Error: Import of '{module}' is restricted for security reasons."

            # Prevent file operations
            if isinstance(node, (ast.Call)):
                if isinstance(node.func, ast.Name) and node.func.id in [
                    "open",
                    "eval",
                    "exec",
                ]:
                    return f"Error: Function '{node.func.id}' is restricted for security reasons."

                # Check attribute access for file operations
                if isinstance(node.func, ast.Attribute) and node.func.attr in [
                    "read",
                    "write",
                    "open",
                    "exec",
                    "eval",
                ]:
                    return f"Error: Method '{node.func.attr}' is restricted for security reasons."
    except SyntaxError as e:
        return f"Syntax Error: {str(e)}"

    # Capture stdout and stderr
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()

    # Execute the code
    try:
        # Import modules we want to make available
        import math
        import random
        import datetime
        import json
        import re

        # Set up a controlled globals dictionary with allowed built-ins
        restricted_builtins = ["open", "exec", "eval", "__import__", "compile", "input"]

        # Create a safe namespace with built-in functions and our imported modules
        safe_globals = {
            "math": math,
            "random": random,
            "datetime": datetime,
            "json": json,
            "re": re,
            "range": range,  # Explicitly add range
            "len": len,  # Explicitly add len
            "str": str,  # Explicitly add str
            "int": int,  # Explicitly add int
            "float": float,  # Explicitly add float
            "bool": bool,  # Explicitly add bool
            "list": list,  # Explicitly add list
            "dict": dict,  # Explicitly add dict
            "set": set,  # Explicitly add set
            "tuple": tuple,  # Explicitly add tuple
            "sum": sum,  # Explicitly add sum
            "min": min,  # Explicitly add min
            "max": max,  # Explicitly add max
            "abs": abs,  # Explicitly add abs
            "all": all,  # Explicitly add all
            "any": any,  # Explicitly add any
            "enumerate": enumerate,  # Explicitly add enumerate
            "zip": zip,  # Explicitly add zip
            "sorted": sorted,  # Explicitly add sorted
            "reversed": reversed,  # Explicitly add reversed
            "round": round,  # Explicitly add round
            "divmod": divmod,  # Explicitly add divmod
            "chr": chr,  # Explicitly add chr
            "ord": ord,  # Explicitly add ord
            "__builtins__": {
                name: getattr(__builtins__, name)
                for name in dir(__builtins__)
                if name not in restricted_builtins
            },
        }

        # Add our own safe print function that writes to our buffer
        def safe_print(*args, **kwargs):
            # Remove file if it's in kwargs to ensure it prints to our buffer
            kwargs.pop("file", None)
            # Convert all arguments to strings
            print(*args, file=stdout_buffer, **kwargs)

        safe_globals["print"] = safe_print

        # Execute with redirected stdout/stderr
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            exec(code, safe_globals, {})

        # Get the output
        stdout = stdout_buffer.getvalue()
        stderr = stderr_buffer.getvalue()

        # Format the response
        result = ""
        if stdout:
            result += f"STDOUT:\n{stdout}\n"
        if stderr:
            result += f"STDERR:\n{stderr}\n"

        return (
            result.strip()
            if result.strip()
            else "Code executed successfully with no output."
        )

    except Exception:
        # Get exception and traceback info
        import traceback

        tb = traceback.format_exc()
        return f"Error executing code:\n{tb}"


@tool
async def run_bash_command(context: "AgentContext", command: str):
    """Run a bash command in a sandboxed environment with safety checks.

    Args:
        command: The bash command to execute
    """
    try:
        # Check for potentially dangerous commands
        dangerous_commands = [
            r"\bsudo\b",
        ]
        import re

        if any(re.search(cmd, command) for cmd in dangerous_commands):
            return "Error: This command is not allowed for safety reasons."

        try:
            if not context.sandbox.check_permissions("shell", command):
                return "Error: Operator denied permission."
        except DoSomethingElseError:
            raise  # Re-raise to be handled by higher-level components

        return await _run_bash_command_with_interactive_timeout(context, command)

    except Exception as e:
        return f"Error executing command: {str(e)}"


async def run_bash_command_with_live_streaming(
    context: "AgentContext", command: str, initial_timeout: int = 30
):
    """Run a bash command with interactive timeout handling and live output streaming.

    This function creates its own Live display for real-time output streaming.

    Args:
        context: The agent context
        command: The bash command to execute
        initial_timeout: Initial timeout in seconds before prompting user
    """
    from rich.live import Live
    from rich.text import Text

    # Create live display
    live_content = Text("Starting command execution...")

    with Live(live_content, refresh_per_second=4) as live:
        return await _run_bash_command_with_interactive_timeout(
            context, command, initial_timeout, live=live
        )


async def _run_bash_command_with_interactive_timeout(
    context: "AgentContext", command: str, initial_timeout: int = 30, live=None
):
    """Run a bash command with interactive timeout handling.

    Args:
        context: The agent context
        command: The bash command to execute
        initial_timeout: Initial timeout in seconds before prompting user
        live: Optional Rich Live instance for real-time output streaming
    """
    import asyncio
    import time
    import io
    import threading
    from queue import Queue

    # Start the process
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
    import time

    # Give threads a moment to finish
    time.sleep(0.1)

    # Collect any remaining output
    _collect_output_batch(stdout_queue, stderr_queue, stdout_buffer, stderr_buffer)
