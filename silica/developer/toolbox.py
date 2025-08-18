import json
from typing import Callable, List

from anthropic.types import MessageParam

from .context import AgentContext
import subprocess
import inspect
from .commit import run_commit
from .sandbox import DoSomethingElseError
from queue import Empty

from .tools import ALL_TOOLS
from .utils import render_tree
from .web.app import run_memory_webapp
from .tools.sessions import list_sessions, print_session_list, resume_session


try:
    from heare.developer.tools.google_auth_cli import GOOGLE_AUTH_CLI_TOOLS
except ImportError:
    GOOGLE_AUTH_CLI_TOOLS = {}


class Toolbox:
    def __init__(self, context: AgentContext, tool_names: List[str] | None = None):
        self.context = context
        self.local = {}  # CLI tools

        if tool_names is not None:
            self.agent_tools = [
                tool for tool in ALL_TOOLS if tool.__name__ in tool_names
            ]
        else:
            self.agent_tools = ALL_TOOLS

        # Register CLI tools
        self.register_cli_tool("help", self._help, "Show help", aliases=["h"])
        self.register_cli_tool("tips", self._tips, "Show usage tips and tricks")
        self.register_cli_tool(
            "add", self._add, "Add file or directory to sandbox", aliases=["a"]
        )
        self.register_cli_tool(
            "remove",
            self._remove,
            "Remove a file or directory from sandbox",
            aliases=["rm", "delete"],
        )
        self.register_cli_tool(
            "list", self._list, "List contents of the sandbox", aliases=["ls", "tree"]
        )
        self.register_cli_tool(
            "dump",
            self._dump,
            "Render the system message, tool specs, and chat history",
        )
        self.register_cli_tool(
            "prompt",
            self._prompt,
            "Show the current system prompt",
        )
        self.register_cli_tool(
            "exec",
            self._exec,
            "Execute a bash command and optionally add it to tool result buffer",
        )
        self.register_cli_tool(
            "commit", self._commit, "Generate and execute a commit message"
        )
        self.register_cli_tool("memory", self._memory, "Interact with agent memory")
        self.register_cli_tool(
            "model", self._model, "Display or change the current AI model"
        )

        self.register_cli_tool(
            "view-memory", self._launch_memory_webapp, "Launch memory webapp"
        )

        # Register session management CLI tools
        self.register_cli_tool(
            "sessions",
            self._list_sessions,
            "List available developer sessions",
            aliases=["ls-sessions"],
        )
        self.register_cli_tool(
            "resume", self._resume_session, "Resume a previous developer session"
        )

        # Register Google Auth CLI tools
        for name, tool_info in GOOGLE_AUTH_CLI_TOOLS.items():
            self.register_cli_tool(
                name,
                tool_info["func"],
                tool_info["docstring"],
                aliases=tool_info.get("aliases", []),
            )

        # Schema for agent tools
        self.agent_schema = self.schemas()

    def register_cli_tool(
        self,
        name: str,
        func: Callable,
        docstring: str = None,
        aliases: List[str] = None,
    ):
        """Register a CLI tool with the toolbox."""
        tool_info = {
            "name": name,
            "docstring": docstring or inspect.getdoc(func),
            "invoke": func,
            "aliases": aliases or [name],
        }
        self.local[name] = tool_info
        if aliases:
            for alias in aliases:
                self.local[alias] = tool_info

    async def invoke_cli_tool(
        self,
        name: str,
        arg_str: str,
        chat_history: list[MessageParam] = None,
        confirm_to_add: bool = True,
    ) -> tuple[str, bool]:
        content = self.local[name]["invoke"](
            sandbox=self.context.sandbox,
            user_interface=self.context.user_interface,
            user_input=arg_str,
            chat_history=chat_history or [],
        )

        self.context.user_interface.handle_system_message(content, markdown=False)
        add_to_buffer = confirm_to_add
        if confirm_to_add and content and content.strip():
            add_to_buffer = (
                (
                    (
                        await self.context.user_interface.get_user_input(
                            "[bold]Add command and output to conversation? (y/[red]N[/red]): [/bold]"
                        )
                    )
                    .strip()
                    .lower()
                )
                == "y"
                and content
                and content.strip()
            )

        return content, add_to_buffer

    async def invoke_agent_tool(self, tool_use):
        """Invoke an agent tool based on the tool use object."""
        from .tools.framework import invoke_tool
        from .sandbox import DoSomethingElseError

        try:
            # Ensure tool_use has the expected attributes before proceeding
            if not hasattr(tool_use, "name") or not hasattr(tool_use, "input"):
                tool_use_id = getattr(tool_use, "id", "unknown_id")
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "Invalid tool specification: missing required attributes",
                }

            # Convert agent tools to a list matching tools format
            return await invoke_tool(self.context, tool_use, tools=self.agent_tools)
        except DoSomethingElseError:
            # Let the exception propagate up to the agent to be handled
            raise
        except Exception as e:
            # Handle any other exceptions that might occur
            tool_use_id = getattr(tool_use, "id", "unknown_id")
            tool_name = getattr(tool_use, "name", "unknown_tool")
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": f"Error invoking tool '{tool_name}': {str(e)}",
            }

    async def invoke_agent_tools(self, tool_uses):
        """Invoke multiple agent tools, potentially in parallel."""
        import asyncio
        from .tools.framework import invoke_tool
        from .sandbox import DoSomethingElseError

        # Log tool usage for user feedback
        for tool_use in tool_uses:
            tool_name = getattr(tool_use, "name", "unknown_tool")
            tool_input = getattr(tool_use, "input", {})
            self.context.user_interface.handle_tool_use(tool_name, tool_input)

        # All tools can now be executed in parallel since each tool
        # manages its own concurrency limits via the @tool decorator
        parallel_tools = list(tool_uses)
        sequential_tools = []

        results = []

        try:
            # Execute parallel tools concurrently if any exist
            if parallel_tools:
                if len(parallel_tools) > 1:
                    self.context.user_interface.handle_system_message(
                        f"Executing {len(parallel_tools)} tools in parallel..."
                    )

                # Create coroutines for parallel execution
                parallel_coroutines = [
                    invoke_tool(self.context, tool_use, tools=self.agent_tools)
                    for tool_use in parallel_tools
                ]

                # Execute in parallel with proper cancellation handling
                try:
                    parallel_results = await asyncio.gather(
                        *parallel_coroutines, return_exceptions=True
                    )
                except (KeyboardInterrupt, asyncio.CancelledError):
                    # Cancel all running tasks
                    for coro in parallel_coroutines:
                        if hasattr(coro, "cancel"):
                            coro.cancel()
                    raise KeyboardInterrupt("Tool execution interrupted by user")

                # Handle results and exceptions
                for tool_use, result in zip(parallel_tools, parallel_results):
                    # Check for cancellation/interruption first (CancelledError is BaseException, not Exception)
                    if isinstance(result, (KeyboardInterrupt, asyncio.CancelledError)):
                        raise KeyboardInterrupt("Tool execution interrupted by user")
                    elif isinstance(result, Exception):
                        if isinstance(result, DoSomethingElseError):
                            raise result  # Propagate DoSomethingElseError

                        # Convert other exceptions to error results
                        tool_use_id = getattr(tool_use, "id", "unknown_id")
                        tool_name = getattr(tool_use, "name", "unknown_tool")
                        result = {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": f"Error invoking tool '{tool_name}': {str(result)}",
                        }
                    results.append(result)

            # Execute sequential tools one by one
            if sequential_tools:
                self.context.user_interface.handle_system_message(
                    f"Executing {len(sequential_tools)} tools sequentially..."
                )

                for tool_use in sequential_tools:
                    try:
                        result = await invoke_tool(
                            self.context, tool_use, tools=self.agent_tools
                        )
                        results.append(result)
                    except (KeyboardInterrupt, asyncio.CancelledError):
                        raise KeyboardInterrupt("Tool execution interrupted by user")
                    except DoSomethingElseError:
                        raise  # Propagate DoSomethingElseError
                    except Exception as e:
                        # Handle any other exceptions that might occur
                        tool_use_id = getattr(tool_use, "id", "unknown_id")
                        tool_name = getattr(tool_use, "name", "unknown_tool")
                        result = {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": f"Error invoking tool '{tool_name}': {str(e)}",
                        }
                        results.append(result)

            # Reorder results to match original tool_uses order
            tool_use_to_result = {}
            result_index = 0

            # Map parallel results
            for tool_use in parallel_tools:
                tool_use_to_result[id(tool_use)] = results[result_index]
                result_index += 1

            # Map sequential results
            for tool_use in sequential_tools:
                tool_use_to_result[id(tool_use)] = results[result_index]
                result_index += 1

            # Return results in original order
            ordered_results = []
            for tool_use in tool_uses:
                ordered_results.append(tool_use_to_result[id(tool_use)])

            return ordered_results

        except (KeyboardInterrupt, asyncio.CancelledError):
            # Let KeyboardInterrupt propagate to the agent
            raise KeyboardInterrupt("Tool execution interrupted by user")
        except DoSomethingElseError:
            # Let the exception propagate up to the agent to be handled
            raise
        except Exception as e:
            # Handle any other exceptions that might occur at the batch level
            error_message = f"Error in batch tool execution: {str(e)}"
            return [
                {
                    "type": "tool_result",
                    "tool_use_id": getattr(tool_use, "id", "unknown_id"),
                    "content": error_message,
                }
                for tool_use in tool_uses
            ]

    # CLI Tools
    def _help(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Show help"""
        help_text = "## Available commands:\n"
        help_text += "- **/restart** - Clear chat history and start over\n"
        help_text += "- **/quit** - Quit the chat\n"

        displayed_tools = set()
        for tool_name, spec in self.local.items():
            if tool_name not in displayed_tools:
                aliases = ", ".join(
                    [f"/{alias}" for alias in spec["aliases"] if alias != tool_name]
                )
                alias_text = f" (aliases: {aliases})" if aliases else ""
                help_text += f"- **/{tool_name}**{alias_text} - {spec['docstring']}\n"
                displayed_tools.add(tool_name)
                displayed_tools.update(spec["aliases"])

        help_text += "\nYou can ask the AI to read, write, or list files/directories\n"
        help_text += (
            "You can also ask the AI to run bash commands (with some restrictions)"
        )

        user_interface.handle_system_message(help_text)

    def _tips(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Show usage tips and tricks"""
        tips_text = """## Usage Tips and Tricks

**Multi-line Input:**
* Start with `{` on a new line, enter your content, and end with `}` on a new line
* Perfect for pasting code snippets or long descriptions

**Output Formatting:**
* All output supports Markdown formatting
* Code blocks are automatically syntax highlighted
* Use triple backticks with language for best highlighting

**File Management:**
* Use `@filename.txt` in your messages to reference files (with tab completion)
* The AI can read, write, and edit files in your project
* Use `/add` and `/remove` to manage which files are in the sandbox context

**Command Shortcuts:**
* Use `/exec` to run shell commands quickly
* Use `/commit` to auto-generate git commit messages
* Use `/model` to see or change the AI model
* Use `/memory` to save important facts or see your memory tree

**Session Management:**
* Use `/sessions` to list previous chat sessions
* Use `/resume <session-id>` to continue where you left off
* Session history is automatically saved and organized by directory

**Efficiency Tips:**
* The AI can work with multiple files simultaneously
* Ask for explanations of code, suggestions for improvements, or help debugging
* Use natural language - describe what you want to accomplish
* The AI understands your project context and can maintain consistency

**File References:**
* Type `@` followed by a path to get tab completion for file names
* The AI will automatically read referenced files when needed
* Example: "Please review the logic in @src/main.py"

**Advanced Features:**
* Use `/view-memory` to launch the web-based memory browser
* The AI maintains long-term memory between sessions
* Context is automatically managed - older messages are compressed when needed
"""

        user_interface.handle_system_message(tips_text)

    def _add(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Add file or directory to sandbox"""
        path = user_input[4:].strip()
        sandbox.get_directory_listing()  # This will update the internal listing
        user_interface.handle_system_message(f"Added {path} to sandbox")
        self._list(user_interface, sandbox)

    def _remove(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Remove a file or directory from sandbox"""
        path = user_input[3:].strip()
        sandbox.get_directory_listing()  # This will update the internal listing
        user_interface.handle_system_message(f"Removed {path} from sandbox")
        self._list(user_interface, sandbox)

    def _list(self, user_interface, sandbox, *args, **kwargs):
        """List contents of the sandbox"""
        sandbox_contents = sandbox.get_directory_listing()
        content = "[bold cyan]Sandbox contents:[/bold cyan]\n" + "\n".join(
            f"[cyan]{item}[/cyan]" for item in sandbox_contents
        )
        user_interface.handle_system_message(content, markdown=False)

    def _dump(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Render the system message, tool specs, and chat history"""
        from .prompt import create_system_message
        from .agent_loop import _inline_latest_file_mentions

        content = "[bold cyan]System Message:[/bold cyan]\n\n"
        content += json.dumps(create_system_message(self.context), indent=2)
        content += "\n\n[bold cyan]Tool Specifications:[/bold cyan]\n"
        content += json.dumps(self.agent_schema, indent=2)
        content += (
            "\n\n[bold cyan]Chat History (with inlined file contents):[/bold cyan]\n"
        )
        inlined_history = _inline_latest_file_mentions(kwargs["chat_history"])
        for message in inlined_history:
            if isinstance(message["content"], str):
                content += f"\n[bold]{message['role']}:[/bold] {message['content']}"
            elif isinstance(message["content"], list):
                content += f"\n[bold]{message['role']}:[/bold]"
                for block in message["content"]:
                    if isinstance(block, dict) and "text" in block:
                        content += f"\n{block['text']}"

        return content

    def _prompt(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Show the current system prompt"""
        from .prompt import create_system_message

        content = "[bold cyan]Current System Prompt:[/bold cyan]\n\n"
        system_message = create_system_message(self.context)
        content += json.dumps(system_message, indent=2)

        return content

    def _exec(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Execute a bash command and optionally add it to tool result buffer"""
        # For CLI use, user_input is the raw command (no '/exec' prefix)
        command = user_input.strip() if user_input else ""
        if command.startswith("/exec "):
            command = command[
                6:
            ].strip()  # Remove '/exec ' from the beginning if present
        result = self._run_bash_command(command)

        user_interface.handle_system_message(f"Command Output:\n{result}")

        # Return the result for potential addition to tool buffer
        # The calling code will handle the confirmation prompt
        chat_entry = f"Executed bash command: {command}\n\nCommand output:\n{result}"
        return chat_entry

    def _commit(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Generate and execute a commit message"""
        # Stage all unstaged changes
        stage_result = self._run_bash_command("git add -A")
        user_interface.handle_system_message("Staged all changes:\n" + stage_result)

        # Commit the changes
        result = run_commit()
        user_interface.handle_system_message(result)

    # Agent Tools
    def _run_bash_command(self, command: str) -> str:
        """Synchronous version with enhanced timeout handling for CLI use"""
        try:
            # Check for potentially dangerous commands
            dangerous_commands = [
                r"\bsudo\b",
            ]
            import re

            if any(re.search(cmd, command) for cmd in dangerous_commands):
                return "Error: This command is not allowed for safety reasons."

            if not self.context.sandbox.check_permissions("shell", command):
                return "Error: Operator denied permission."

            # Use enhanced timeout handling for CLI too
            return self._run_bash_command_with_interactive_timeout_sync(command)

        except Exception as e:
            return f"Error executing command: {str(e)}"

    def _run_bash_command_with_interactive_timeout_sync(
        self, command: str, initial_timeout: int = 30
    ) -> str:
        """Synchronous version of interactive timeout handling for CLI use"""
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
                self._collect_remaining_output_sync(
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
            self._collect_output_batch_sync(
                stdout_queue, stderr_queue, stdout_buffer, stderr_buffer
            )

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

                self.context.user_interface.handle_system_message(
                    status_msg, markdown=False
                )

                # Prompt user for action (synchronous)
                choice = (
                    input(
                        "Command is still running. Choose action:\n"
                        f"  [C]ontinue waiting ({initial_timeout}s more)\n"
                        "  [K]ill the process\n"
                        "  [B]ackground (continue but return current output)\n"
                        "Choice (C/K/B): "
                    )
                    .strip()
                    .upper()
                )

                if choice == "K":
                    # Kill the process
                    try:
                        process.terminate()
                        # Give it a moment to terminate gracefully
                        time.sleep(1)
                        if process.poll() is None:
                            process.kill()

                        # Collect any final output
                        self._collect_remaining_output_sync(
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
                    output += "Note: Process continues running but output capture has stopped.\n"

                    stdout_content = stdout_buffer.getvalue()
                    stderr_content = stderr_buffer.getvalue()

                    if stdout_content:
                        output += f"STDOUT (so far):\n{stdout_content}\n"
                    if stderr_content:
                        output += f"STDERR (so far):\n{stderr_content}\n"

                    return output

                else:  # Default to 'C' - continue
                    current_timeout += initial_timeout  # Add the same interval again
                    self.context.user_interface.handle_system_message(
                        f"Continuing to wait for {initial_timeout} more seconds...",
                        markdown=False,
                    )

            # Sleep briefly before next check
            time.sleep(0.5)

    def _collect_output_batch_sync(
        self, stdout_queue, stderr_queue, stdout_buffer, stderr_buffer
    ):
        """Collect a batch of output from the queues (synchronous version)."""
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

    def _collect_remaining_output_sync(
        self, stdout_queue, stderr_queue, stdout_buffer, stderr_buffer
    ):
        """Collect any remaining output from the queues (synchronous version)."""
        import time

        # Give threads a moment to finish
        time.sleep(0.1)

        # Collect any remaining output
        self._collect_output_batch_sync(
            stdout_queue, stderr_queue, stdout_buffer, stderr_buffer
        )

    async def _run_bash_command_async(self, command: str) -> str:
        """Async version with interactive timeout handling"""
        try:
            # Check for potentially dangerous commands
            dangerous_commands = [
                r"\bsudo\b",
            ]
            import re

            if any(re.search(cmd, command) for cmd in dangerous_commands):
                return "Error: This command is not allowed for safety reasons."

            try:
                if not self.context.sandbox.check_permissions("shell", command):
                    return "Error: Operator denied permission."
            except DoSomethingElseError:
                raise  # Re-raise to be handled by higher-level components

            # Import the enhanced function from tools.repl
            from .tools.repl import _run_bash_command_with_interactive_timeout

            return await _run_bash_command_with_interactive_timeout(
                self.context, command
            )
        except Exception as e:
            return f"Error executing command: {str(e)}"

    def _memory(self, user_interface, sandbox, user_input, *args, **kwargs) -> str:
        if user_input:
            from .tools.subagent import agent

            result = agent(
                context=self.context,
                prompt=f"Store this fact in your memory.\n\n{user_input}",
                model="light",
            )
            return result
        else:
            lines = []
            render_tree(
                lines, self.context.memory_manager.get_tree(depth=-1), is_root=True
            )
            return "\n".join(lines)

    def _launch_memory_webapp(
        self, user_interface, sandbox, user_input, *args, **kwargs
    ):
        run_memory_webapp()

    def _list_sessions(self, user_interface, sandbox, user_input, *args, **kwargs):
        """List available developer sessions."""
        # Extract optional workdir filter
        workdir = user_input.strip() if user_input.strip() else None

        # Get the list of sessions'1583628'
        sessions = list_sessions(workdir)

        # Print the formatted list
        print_session_list(sessions)

        return f"Listed {len(sessions)} developer sessions" + (
            f" for {workdir}" if workdir else ""
        )

    def _resume_session(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Resume a previous developer session."""
        session_id = user_input.strip()

        if not session_id:
            user_interface.handle_system_message(
                "Please provide a session ID to resume", markdown=False
            )
            return "Error: No session ID provided"

        # Attempt to resume the session
        success = resume_session(session_id)

        if not success:
            return f"Failed to resume session {session_id}"

        return f"Resumed session {session_id}"

    def _model(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Display or change the current AI model"""
        from .models import model_names, get_model, MODEL_MAP

        # If no argument provided, show current model
        if not user_input.strip():
            current_model = self.context.model_spec
            model_name = current_model["title"]

            # Find the short name for this model
            short_name = None
            for short, spec in MODEL_MAP.items():
                if spec["title"] == model_name:
                    short_name = short
                    break

            info = f"**Current Model:** {model_name}"
            if short_name:
                info += f" ({short_name})"

            info += f"\n\n**Max Tokens:** {current_model['max_tokens']}"
            info += (
                f"\n\n**Context Window:** {current_model['context_window']:,} tokens"
            )
            info += "\n\n**Pricing:**"
            info += f"\n\n  - Input: ${current_model['pricing']['input']:.2f}/MTok"
            info += f"\n\n  - Output: ${current_model['pricing']['output']:.2f}/MTok"
            user_interface.handle_system_message(info)

            return None

        # Parse the model argument
        new_model_name = user_input.strip()

        # Check if it's a valid model
        try:
            new_model_spec = get_model(new_model_name)

            # Update the context's model specification
            self.context.model_spec = new_model_spec

            # Find the short name for this model
            short_name = None
            for short, spec in MODEL_MAP.items():
                if spec["title"] == new_model_spec["title"]:
                    short_name = short
                    break

            info = f"**Model changed to:** {new_model_spec['title']}"
            if short_name:
                info += f" ({short_name})"

            info += f"\n**Max Tokens:** {new_model_spec['max_tokens']}"
            info += f"\n**Context Window:** {new_model_spec['context_window']:,} tokens"
            info += "\n**Pricing:**"
            info += f"\n  - Input: ${new_model_spec['pricing']['input']:.2f}/MTok"
            info += f"\n  - Output: ${new_model_spec['pricing']['output']:.2f}/MTok"

            return info

        except ValueError as e:
            available_models = model_names()
            short_names = [name for name in available_models if name in MODEL_MAP]
            full_names = [spec["title"] for spec in MODEL_MAP.values()]

            error_msg = f"**Error:** {str(e)}\n\n"
            error_msg += "**Available short names:**\n"
            for name in sorted(short_names):
                error_msg += f"  - {name}\n"
            error_msg += "\n**Available full model names:**\n"
            for name in sorted(set(full_names)):
                error_msg += f"  - {name}\n"

            return error_msg

    def schemas(self, enable_caching: bool = True) -> List[dict]:
        """Generate schemas for all tools in the toolbox.

        Returns a list of schema dictionaries matching the format of TOOLS_SCHEMA.
        Each schema has name, description, and input_schema with properties and required fields.
        """
        schemas = []
        for tool in self.agent_tools:
            if hasattr(tool, "schema"):
                schemas.append(tool.schema())
        if schemas and enable_caching:
            schemas[-1]["cache_control"] = {"type": "ephemeral"}
        return schemas
