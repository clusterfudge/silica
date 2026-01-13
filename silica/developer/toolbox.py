import json
import os
from typing import Callable, List, Dict

from anthropic.types import MessageParam

from .context import AgentContext
import subprocess
import inspect
from .commit import run_commit
from .sandbox import DoSomethingElseError
from queue import Empty

from .tools import ALL_TOOLS
from .tools.framework import get_tool_group
from .tools.permissions import PermissionsManager
from .utils import render_tree
from .web.app import run_memory_webapp
from .tools.sessions import list_sessions, print_session_list, resume_session
from .tools.user_tools import (
    discover_tools,
    invoke_user_tool,
    find_tool,
    DiscoveredTool,
)


try:
    from heare.developer.tools.google_auth_cli import GOOGLE_AUTH_CLI_TOOLS
except ImportError:
    GOOGLE_AUTH_CLI_TOOLS = {}


class Toolbox:
    def __init__(
        self,
        context: AgentContext,
        tool_names: List[str] | None = None,
        tools: List[str] | None = None,
        skip_user_tool_auth: bool = False,
        show_warnings: bool = True,
    ):
        self.context = context
        self.local = {}  # CLI tools

        if tool_names is not None:
            self.agent_tools = [
                tool for tool in ALL_TOOLS if tool.__name__ in tool_names
            ]
        else:
            self.agent_tools = ALL_TOOLS

        # Filter out persona tools if only built-in persona is active (no persona.md)
        from pathlib import Path

        if context.history_base_dir is not None and isinstance(
            context.history_base_dir, Path
        ):
            persona_file = context.history_base_dir / "persona.md"
            if not persona_file.exists():
                # Built-in persona only - remove persona editing tools
                self.agent_tools = [
                    tool
                    for tool in self.agent_tools
                    if tool.__name__ not in ["read_persona", "write_persona"]
                ]

        # Load permissions manager
        dwr_mode = getattr(context, "dwr_mode", False)

        # Only apply permissions if we have a valid persona directory
        if context.history_base_dir is not None:
            self.permissions_manager = PermissionsManager(
                context.history_base_dir, dwr_mode=dwr_mode
            )
            # Filter built-in tools based on permissions
            self.agent_tools = self.permissions_manager.filter_tools(self.agent_tools)
        else:
            self.permissions_manager = None

        # Discover user-created tools from ~/.silica/tools/
        self.user_tools: Dict[str, DiscoveredTool] = {}
        self._skip_user_tool_auth = skip_user_tool_auth
        self._show_warnings = show_warnings
        self._discover_user_tools()
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
            "sandbox",
            self._sandbox_debug,
            "Show sandbox configuration and debug information",
            aliases=["debug"],
        )

        self.register_cli_tool(
            "info",
            self._info,
            "Show statistics about the current session",
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

        # Register compaction CLI tools
        self.register_cli_tool(
            "compact",
            self._compact,
            "Explicitly trigger full conversation compaction",
        )
        self.register_cli_tool(
            "mc",
            self._micro_compact,
            "Micro-compact: summarize first N turns and keep the rest (default N=3)",
        )

        # Register permission management CLI tools
        self.register_cli_tool(
            "permissions",
            self._permissions,
            "Manage tool permissions for this persona",
            aliases=["perms"],
        )
        self.register_cli_tool(
            "groups",
            self._list_groups,
            "List all available tool groups and their tools",
        )

        # Register Google Auth CLI tools
        for name, tool_info in GOOGLE_AUTH_CLI_TOOLS.items():
            self.register_cli_tool(
                name,
                tool_info["func"],
                tool_info["docstring"],
                aliases=tool_info.get("aliases", []),
            )

        # Register tool authorization CLI tool
        self.register_cli_tool(
            "auth-tool",
            self._auth_tool,
            "Authorize a user tool that requires authentication",
        )

        # Register tools management CLI tool
        self.register_cli_tool(
            "tools",
            self._tools,
            "List available tools and manage user tool authorization",
        )

        # Register plan mode CLI tool
        self.register_cli_tool(
            "plan",
            self._plan,
            "Enter plan mode or manage plans",
        )

        # Note: agent_schema is now a property that dynamically re-discovers user tools
        # This ensures newly created user tools are immediately available

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
        import inspect

        result = self.local[name]["invoke"](
            sandbox=self.context.sandbox,
            user_interface=self.context.user_interface,
            user_input=arg_str,
            chat_history=chat_history or [],
        )

        # Handle async CLI tools
        if inspect.iscoroutine(result):
            content = await result
        else:
            content = result

        # Handle special return values:
        # - tuple (content, auto_add): content with explicit add flag
        # - str: normal content, follows confirm_to_add logic
        # - None/"": no content, don't add to buffer
        auto_add = None
        if isinstance(content, tuple) and len(content) == 2:
            content, auto_add = content

        # If content is empty/None, nothing to add
        if not content or not content.strip():
            return "", False

        # Render output to user (unless auto_add is True, meaning it's agent-bound)
        if auto_add is not True:
            render_as_markdown = name == "info"
            self.context.user_interface.handle_system_message(
                content, markdown=render_as_markdown
            )

        # Determine whether to add to buffer
        if auto_add is not None:
            # Explicit flag from tool
            add_to_buffer = auto_add
        elif confirm_to_add:
            # Ask user for confirmation
            add_to_buffer = (
                (
                    await self.context.user_interface.get_user_input(
                        "[bold]Add command and output to conversation? (y/[red]N[/red]): [/bold]"
                    )
                )
                .strip()
                .lower()
            ) == "y"
        else:
            add_to_buffer = False

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

            tool_name = tool_use.name
            tool_use_id = getattr(tool_use, "id", "unknown_id")

            # Check if this is a user-created tool (cached)
            if tool_name in self.user_tools:
                return await self._invoke_user_tool(tool_use)

            # Not in cache - try dynamic lookup for newly created user tools
            user_tool = find_tool(tool_name)
            if user_tool and user_tool.spec:
                # Add to cache for future invocations
                self.user_tools[tool_name] = user_tool
                return await self._invoke_user_tool(tool_use)

            # Fall back to built-in tool invocation (handles unknown tools too)
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

    async def _invoke_user_tool(self, tool_use) -> dict:
        """Invoke a user-created tool."""
        import asyncio

        tool_name = tool_use.name
        tool_use_id = getattr(tool_use, "id", "unknown_id")
        args = tool_use.input or {}

        # Run the user tool in a thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: invoke_user_tool(tool_name, args),
        )

        if result.success:
            # Try to parse JSON output for better formatting
            try:
                parsed = json.loads(result.output)
                content = json.dumps(parsed, indent=2)
            except (json.JSONDecodeError, TypeError):
                content = (
                    result.output.strip()
                    if result.output
                    else "Tool completed successfully."
                )
        else:
            # Format error response
            error_parts = []
            error_parts.append(f"Tool execution failed (exit code {result.exit_code})")
            if result.output:
                error_parts.append(f"Stdout:\n{result.output.strip()}")
            if result.error:
                error_parts.append(f"Stderr:\n{result.error.strip()}")
            content = "\n\n".join(error_parts)

        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
        }

    async def invoke_agent_tools(self, tool_uses):
        """Invoke multiple agent tools, potentially in parallel."""
        import asyncio
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
                # Note: Use invoke_agent_tool which handles both built-in and user tools
                parallel_coroutines = [
                    self.invoke_agent_tool(tool_use) for tool_use in parallel_tools
                ]

                # Execute in parallel with proper cancellation handling
                # Note: asyncio.gather with return_exceptions=True will not raise exceptions
                # but will instead return them in the results list
                parallel_results = await asyncio.gather(
                    *parallel_coroutines, return_exceptions=True
                )

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
                        # Use invoke_agent_tool which handles both built-in and user tools
                        result = await self.invoke_agent_tool(tool_use)
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
        help_text += (
            "- **/compact** - Explicitly trigger full conversation compaction\n"
        )
        help_text += "- **/mc [N]** - Micro-compact: summarize first N turns (default 3) and keep the rest\n"

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

**Thinking Mode (Extended Thinking API):**
* Press **Ctrl+T** to cycle through thinking modes: off → 💭 normal (8k) → 🧠 ultra (20k) → off
* When enabled, the AI thinks deeply before responding (costs 3x input pricing)
* The prompt shows the current mode: `💭 $0.00 >` (normal) or `🧠 $0.00 >` (ultra)
* Thinking content is displayed in a collapsible panel after responses

**Command Shortcuts:**
* Use `/exec` to run shell commands quickly
* Use `/commit` to auto-generate git commit messages
* Use `/model` to see or change the AI model
* Use `/memory` to save important facts or see your memory tree

**Session Management:**
* Use `/sessions` to list previous chat sessions
* Use `/resume <session-id>` to continue where you left off
* Session history is automatically saved and organized by directory

**Conversation Compaction:**
* Use `/compact` to manually compress the entire conversation
* Use `/mc [N]` to micro-compact just the first N turns (default 3) while keeping the rest
* Compaction helps manage token usage in long conversations
* Automatic compaction triggers at 65% of context window

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
        for msg_idx, message in enumerate(inlined_history):
            content += f"\n\n[bold]Message {msg_idx} ({message['role']}):[/bold]"

            if isinstance(message["content"], str):
                content += f"\n  [text] {message['content'][:100]}..."
            elif isinstance(message["content"], list):
                content += f"\n  Content blocks: {len(message['content'])}"
                for block_idx, block in enumerate(message["content"]):
                    # Get block type
                    block_type = None
                    if isinstance(block, dict):
                        block_type = block.get("type", "unknown")
                    elif hasattr(block, "type"):
                        block_type = block.type
                    else:
                        block_type = type(block).__name__

                    content += f"\n    [{block_idx}] {block_type}"

                    # Show preview of content
                    if isinstance(block, dict):
                        if "text" in block:
                            preview = block["text"][:100]
                            content += f": {preview}{'...' if len(block['text']) > 100 else ''}"
                        elif "thinking" in block:
                            content += (
                                f" (signature: {block.get('signature', 'N/A')[:20]}...)"
                            )
                        elif "tool_use" in block or block_type == "tool_use":
                            content += f" (name: {block.get('name', 'N/A')})"
                        elif "tool_result" in block or block_type == "tool_result":
                            content += f" (tool_use_id: {block.get('tool_use_id', 'N/A')[:20]}...)"
                    elif hasattr(block, "text"):
                        preview = block.text[:100]
                        content += (
                            f": {preview}{'...' if len(block.text) > 100 else ''}"
                        )
                    elif hasattr(block, "thinking"):
                        content += f" (signature: {block.signature[:20] if hasattr(block, 'signature') else 'N/A'}...)"
                    elif hasattr(block, "name"):
                        content += f" (name: {block.name})"

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

            if not self.context.sandbox.check_permissions(
                "shell", command, group="Shell"
            ):
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

        # Get history_base_dir from context (persona-aware)
        history_base_dir = getattr(self.context, "history_base_dir", None)

        # Get the list of sessions
        sessions = list_sessions(workdir, history_base_dir=history_base_dir)

        # Print the formatted list
        print_session_list(sessions)

        return f"Listed {len(sessions)} developer sessions" + (
            f" for {workdir}" if workdir else ""
        )

    async def _resume_session(
        self, user_interface, sandbox, user_input, *args, **kwargs
    ):
        """Resume a previous developer session."""
        from .tools.sessions import interactive_resume

        session_id = user_input.strip()

        # Get history_base_dir from context (persona-aware)
        history_base_dir = getattr(self.context, "history_base_dir", None)

        # If no session ID provided, show interactive menu
        if not session_id:
            # Get list of sessions first to check if any exist
            sessions = list_sessions(history_base_dir=history_base_dir)

            if not sessions:
                user_interface.handle_system_message(
                    "No sessions found to resume.", markdown=False
                )
                return "No sessions available"

            # Show interactive menu
            selected_id = await interactive_resume(
                user_interface=user_interface,
                history_base_dir=history_base_dir,
            )

            if not selected_id:
                user_interface.handle_system_message(
                    "Resume cancelled.", markdown=False
                )
                return "Resume cancelled"

            session_id = selected_id

        # Attempt to resume the session
        success = resume_session(session_id, history_base_dir=history_base_dir)

        if not success:
            return f"Failed to resume session {session_id}"

        return f"Resumed session {session_id}"

    def _sandbox_debug(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Show sandbox configuration and debug information."""
        from .tools.sandbox_debug import sandbox_debug

        # Call the actual sandbox_debug tool function
        result = sandbox_debug(self.context)

        # Return the result for display
        return result

    def _info(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Show statistics about the current session."""
        from datetime import datetime
        from pathlib import Path

        # Get session information
        session_id = self.context.session_id
        parent_session_id = self.context.parent_session_id

        # Get persona name from history_base_dir
        persona_name = "default"
        if self.context.history_base_dir:
            history_base_dir = (
                Path(self.context.history_base_dir)
                if not isinstance(self.context.history_base_dir, Path)
                else self.context.history_base_dir
            )
            # Extract persona name from path like ~/.silica/personas/{persona_name}
            if history_base_dir.parent.name == "personas":
                persona_name = history_base_dir.name
        else:
            history_base_dir = Path.home() / ".silica" / "personas" / "default"

        # Get model information
        model_spec = self.context.model_spec
        model_name = model_spec["title"]
        max_tokens = model_spec["max_tokens"]
        context_window = model_spec["context_window"]

        # Get thinking mode
        thinking_mode = self.context.thinking_mode
        thinking_display = {
            "off": "Off",
            "normal": "💭 Normal (8k tokens)",
            "ultra": "🧠 Ultra (20k tokens)",
        }.get(thinking_mode, thinking_mode)

        # Get usage summary
        usage = self.context.usage_summary()
        total_input_tokens = usage["total_input_tokens"]
        total_output_tokens = usage["total_output_tokens"]
        total_thinking_tokens = usage.get("total_thinking_tokens", 0)
        cached_tokens = usage["cached_tokens"]
        total_cost = usage["total_cost"]
        thinking_cost = usage.get("thinking_cost", 0.0)

        # Get message count
        message_count = len(self.context.chat_history)

        # Calculate conversation size if available
        conversation_size = getattr(self.context, "_last_conversation_size", None)

        # Get session creation and update times if available
        history_dir = history_base_dir / "history"
        context_dir = parent_session_id if parent_session_id else session_id
        history_file = (
            history_dir
            / context_dir
            / ("root.json" if not parent_session_id else f"{session_id}.json")
        )

        created_at = None
        last_updated = None
        root_dir = None

        if history_file.exists():
            try:
                import json

                with open(history_file, "r") as f:
                    session_data = json.load(f)
                    metadata = session_data.get("metadata", {})
                    created_at = metadata.get("created_at")
                    last_updated = metadata.get("last_updated")
                    root_dir = metadata.get("root_dir")
            except Exception:
                pass

        # Format the output
        info = "# Session Information\n\n"

        # Persona
        info += f"**Persona:** `{persona_name}`\n\n"

        # Session IDs
        info += f"**Session ID:** `{session_id}`\n\n"
        if parent_session_id:
            info += f"**Parent Session ID:** `{parent_session_id}`\n\n"

        # Session timestamps
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                info += f"**Created:** {dt.strftime('%Y-%m-%d %H:%M:%S %Z')}\n\n"
            except Exception:
                info += f"**Created:** {created_at}\n\n"

        if last_updated:
            try:
                dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                info += f"**Last Updated:** {dt.strftime('%Y-%m-%d %H:%M:%S %Z')}\n\n"
            except Exception:
                info += f"**Last Updated:** {last_updated}\n\n"

        # Root directory
        if root_dir:
            info += f"**Working Directory:** `{root_dir}`\n\n"

        # Model information
        info += "## Model Configuration\n\n"
        info += f"**Model:** {model_name}\n\n"
        info += f"**Max Tokens:** {max_tokens:,}\n\n"
        info += f"**Context Window:** {context_window:,} tokens\n\n"
        info += f"**Thinking Mode:** {thinking_display}\n\n"

        # Conversation statistics
        info += "## Conversation Statistics\n\n"
        info += f"**Message Count:** {message_count}\n\n"

        if conversation_size:
            usage_percentage = (conversation_size / context_window) * 100
            info += f"**Conversation Size:** {conversation_size:,} tokens ({usage_percentage:.1f}% of context)\n\n"

            # Calculate tokens remaining before compaction threshold (85%)
            compaction_threshold = int(context_window * 0.85)
            tokens_remaining = max(0, compaction_threshold - conversation_size)
            info += f"**Tokens Until Compaction:** {tokens_remaining:,} (threshold: 85%)\n\n"

        # Token usage
        info += "## Token Usage\n\n"
        info += f"**Input Tokens:** {total_input_tokens:,}"
        if cached_tokens > 0:
            info += f" (cached: {cached_tokens:,})"
        info += "\n\n"
        info += f"**Output Tokens:** {total_output_tokens:,}\n\n"

        if total_thinking_tokens > 0:
            info += f"**Thinking Tokens:** {total_thinking_tokens:,}\n\n"

        total_tokens = total_input_tokens + total_output_tokens + total_thinking_tokens
        info += f"**Total Tokens:** {total_tokens:,}\n\n"

        # Cost information
        info += "## Cost Information\n\n"
        info += f"**Session Cost:** ${total_cost:.4f}\n\n"

        if thinking_cost > 0:
            info += f"**Thinking Cost:** ${thinking_cost:.4f}\n\n"
            non_thinking_cost = total_cost - thinking_cost
            info += f"**Non-Thinking Cost:** ${non_thinking_cost:.4f}\n\n"

        # Cost breakdown by model if multiple models used
        if len(usage["model_breakdown"]) > 1:
            info += "### Cost Breakdown by Model\n\n"
            for model, model_usage in usage["model_breakdown"].items():
                info += f"- **{model}:** ${model_usage['total_cost']:.4f}\n\n"

        return info

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

    def _compact(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Explicitly trigger full conversation compaction."""
        from silica.developer.compacter import ConversationCompacter
        import anthropic
        import os
        from dotenv import load_dotenv

        # Check if there's enough conversation to compact
        if len(self.context.chat_history) <= 2:
            return "Error: Not enough conversation history to compact (need more than 2 messages)"

        # Create Anthropic client and compacter instance
        load_dotenv()
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return "Error: ANTHROPIC_API_KEY environment variable not set"

        client = anthropic.Client(api_key=api_key)
        compacter = ConversationCompacter(client=client)
        model_name = self.context.model_spec["title"]

        try:
            # Force compaction
            user_interface.handle_system_message(
                "Compacting conversation (this may take a moment)...", markdown=False
            )

            metadata = compacter.compact_conversation(
                self.context, model_name, force=True
            )

            if metadata:
                # Build result message
                result = "✓ Conversation compacted successfully!\n\n"
                result += f"**Original:** {metadata.original_message_count} messages ({metadata.original_token_count:,} tokens)\n\n"
                result += f"**Compacted:** {metadata.compacted_message_count} messages ({metadata.summary_token_count:,} tokens)\n\n"
                result += f"**Compression ratio:** {metadata.compaction_ratio:.1%}\n\n"
                result += f"**Archive:** {metadata.archive_name}\n\n"

                # Flush the compacted context
                self.context.flush(self.context.chat_history, compact=False)

                return result
            else:
                return "Error: Compaction failed to generate metadata"

        except Exception as e:
            import traceback

            error_details = traceback.format_exc()
            user_interface.handle_system_message(
                f"Compaction failed: {e}\n\n{error_details}", markdown=False
            )
            return f"Error: Compaction failed - {e}"

    def _micro_compact(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Micro-compact: summarize first N turns and keep the rest."""
        from silica.developer.compacter import ConversationCompacter
        from silica.developer.context import AgentContext

        # Parse the number of turns from user_input
        turns_to_compact = 3  # default
        if user_input.strip():
            try:
                turns_to_compact = int(user_input.strip())
                if turns_to_compact < 1:
                    return "Error: Number of turns must be at least 1"
            except ValueError:
                return f"Error: Invalid number '{user_input.strip()}'. Please provide an integer."

        # Calculate number of messages for N turns
        # Turn structure: must start with user and end with user
        # Turn 1: 1 message (user)
        # Turn 2: 3 messages (user, assistant, user)
        # Turn 3: 5 messages (user, assistant, user, assistant, user)
        # Turn N: (2N - 1) messages
        messages_to_compact = (turns_to_compact * 2) - 1

        # Check if there's enough conversation to compact
        if len(self.context.chat_history) <= messages_to_compact:
            return f"Error: Not enough conversation history to micro-compact {turns_to_compact} turns (need more than {messages_to_compact} messages, have {len(self.context.chat_history)})"

        # Separate messages to compact from messages to keep
        messages_to_summarize = self.context.chat_history[:messages_to_compact]
        messages_to_keep = self.context.chat_history[messages_to_compact:]

        # Create Anthropic client and compacter instance
        import anthropic
        import os
        from dotenv import load_dotenv

        load_dotenv()
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return "Error: ANTHROPIC_API_KEY environment variable not set"

        client = anthropic.Client(api_key=api_key)
        compacter = ConversationCompacter(client=client)
        model_name = self.context.model_spec["title"]

        try:
            user_interface.handle_system_message(
                f"Micro-compacting first {turns_to_compact} turns (this may take a moment)...",
                markdown=False,
            )

            # Create a temporary context with just the messages to summarize
            # This allows us to reuse the existing generate_summary method
            temp_context = AgentContext(
                parent_session_id=self.context.parent_session_id,
                session_id=self.context.session_id,
                model_spec=self.context.model_spec,
                sandbox=self.context.sandbox,
                user_interface=self.context.user_interface,
                usage=self.context.usage,
                memory_manager=self.context.memory_manager,
                history_base_dir=self.context.history_base_dir,
            )
            temp_context._chat_history = messages_to_summarize

            # Use the existing generate_summary method
            summary_obj = compacter.generate_summary(temp_context, model_name)
            summary = summary_obj.summary

            # Create new message history with summary + kept messages
            new_messages = [
                {
                    "role": "user",
                    "content": f"### Micro-Compacted Summary (first {turns_to_compact} turns)\n\n{summary}\n\n---\n\nContinuing with remaining conversation...",
                }
            ]
            new_messages.extend(messages_to_keep)

            # Remove orphaned tool_results (tool_results without matching tool_use)
            # This can happen when compaction splits a tool use/result pair
            from silica.developer.compaction_validation import (
                strip_orphaned_tool_blocks,
            )

            new_messages = strip_orphaned_tool_blocks(new_messages)

            # Update the context in place
            self.context._chat_history = new_messages
            self.context._tool_result_buffer.clear()

            # Flush the updated context
            self.context.flush(self.context.chat_history, compact=False)

            # Build result message
            result = "✓ Micro-compaction completed!\n\n"
            result += f"**Compacted:** First {turns_to_compact} turns ({messages_to_compact} messages)\n\n"
            result += f"**Kept:** {len(messages_to_keep)} messages from the rest of the conversation\n\n"
            result += f"**Final message count:** {len(new_messages)} (was {len(self.context.chat_history) + messages_to_compact})\n\n"
            result += f"**Estimated compression:** {messages_to_compact} messages → ~{summary_obj.summary_token_count:,} tokens\n\n"

            return result

        except Exception as e:
            import traceback

            error_details = traceback.format_exc()
            user_interface.handle_system_message(
                f"Micro-compaction failed: {e}\n\n{error_details}", markdown=False
            )
            return f"Error: Micro-compaction failed - {e}"

    def _permissions(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Manage tool permissions for this persona.

        Usage:
            /permissions              - Show current config
            /permissions mode <mode>  - Set mode (allowlist|denylist)
            /permissions allow <name> - Add tool or group to allow list
            /permissions deny <name>  - Add tool or group to deny list
            /permissions remove allow <name> - Remove from allow list
            /permissions remove deny <name>  - Remove from deny list
            /permissions shell allow <cmd>   - Allow a shell command
            /permissions shell deny <cmd>    - Deny a shell command
        """
        if self.permissions_manager is None:
            return "Error: Permissions manager not available (no persona directory configured)"

        args_list = user_input.strip().split() if user_input.strip() else []

        # No arguments - show current config
        if not args_list:
            return self._show_permissions_config()

        command = args_list[0].lower()

        if command == "mode":
            if len(args_list) < 2:
                return "Error: /permissions mode requires a mode argument (allowlist|denylist)"
            mode = args_list[1].lower()
            if mode not in ("allowlist", "denylist"):
                return (
                    f"Error: Invalid mode '{mode}'. Must be 'allowlist' or 'denylist'"
                )
            try:
                self.permissions_manager.set_mode(mode)
                self.permissions_manager.save()
                self._refresh_tools_after_permission_change()
                return f"✓ Permission mode set to '{mode}'"
            except ValueError as e:
                return f"Error: {e}"

        elif command == "allow":
            if len(args_list) < 2:
                return "Error: /permissions allow requires a tool or group name"
            name = args_list[1]
            # Check if it's a group name (capitalized) or tool name
            is_group = self._is_group_name(name)
            if is_group:
                self.permissions_manager.add_to_allow(group=name)
            else:
                self.permissions_manager.add_to_allow(tool_name=name)
            self.permissions_manager.save()
            self._refresh_tools_after_permission_change()
            kind = "group" if is_group else "tool"
            return f"✓ Added {kind} '{name}' to allow list"

        elif command == "deny":
            if len(args_list) < 2:
                return "Error: /permissions deny requires a tool or group name"
            name = args_list[1]
            is_group = self._is_group_name(name)
            if is_group:
                self.permissions_manager.add_to_deny(group=name)
            else:
                self.permissions_manager.add_to_deny(tool_name=name)
            self.permissions_manager.save()
            self._refresh_tools_after_permission_change()
            kind = "group" if is_group else "tool"
            return f"✓ Added {kind} '{name}' to deny list"

        elif command == "remove":
            if len(args_list) < 3:
                return (
                    "Error: /permissions remove requires 'allow' or 'deny' and a name"
                )
            list_type = args_list[1].lower()
            name = args_list[2]
            is_group = self._is_group_name(name)

            if list_type == "allow":
                if is_group:
                    self.permissions_manager.remove_from_allow(group=name)
                else:
                    self.permissions_manager.remove_from_allow(tool_name=name)
                self.permissions_manager.save()
                self._refresh_tools_after_permission_change()
                kind = "group" if is_group else "tool"
                return f"✓ Removed {kind} '{name}' from allow list"
            elif list_type == "deny":
                if is_group:
                    self.permissions_manager.remove_from_deny(group=name)
                else:
                    self.permissions_manager.remove_from_deny(tool_name=name)
                self.permissions_manager.save()
                self._refresh_tools_after_permission_change()
                kind = "group" if is_group else "tool"
                return f"✓ Removed {kind} '{name}' from deny list"
            else:
                return f"Error: Invalid list type '{list_type}'. Use 'allow' or 'deny'"

        elif command == "shell":
            if len(args_list) < 3:
                return (
                    "Error: /permissions shell requires 'allow' or 'deny' and a command"
                )
            action = args_list[1].lower()
            cmd = args_list[2]

            if action == "allow":
                self.permissions_manager.add_shell_command(cmd, allow=True)
                self.permissions_manager.save()
                return f"✓ Added shell command '{cmd}' to allow list"
            elif action == "deny":
                self.permissions_manager.add_shell_command(cmd, allow=False)
                self.permissions_manager.save()
                return f"✓ Added shell command '{cmd}' to deny list"
            else:
                return f"Error: Invalid action '{action}'. Use 'allow' or 'deny'"

        else:
            return f"""Error: Unknown subcommand '{command}'.

Usage:
  /permissions              - Show current config
  /permissions mode <mode>  - Set mode (allowlist|denylist)
  /permissions allow <name> - Add tool or group to allow list
  /permissions deny <name>  - Add tool or group to deny list
  /permissions remove allow <name> - Remove from allow list
  /permissions remove deny <name>  - Remove from deny list
  /permissions shell allow <cmd>   - Allow a shell command
  /permissions shell deny <cmd>    - Deny a shell command"""

    def _show_permissions_config(self) -> str:
        """Show the current permissions configuration."""
        if self.permissions_manager.permissions is None:
            return """**No permissions configured**

No tool_permissions.json file exists for this persona.
Without a permissions file, no tools are available (secure by default).

Use `/permissions mode allowlist` or `/permissions mode denylist` to create one.
Use `/groups` to see available tool groups."""

        p = self.permissions_manager.permissions

        output = "# Tool Permissions Configuration\n\n"
        output += f"**Mode:** `{p.mode}`\n\n"

        # Explain the mode
        if p.mode == "allowlist":
            output += "_Only tools in the allow list (or their groups) are available. Deny list acts as exceptions._\n\n"
        else:
            output += "_All tools are available except those in the deny list._\n\n"

        # Allow list
        output += "## Allow List\n\n"
        if p.allow_tools or p.allow_groups:
            if p.allow_tools:
                output += "**Tools:**\n"
                for tool in sorted(p.allow_tools):
                    output += f"  - `{tool}`\n"
                output += "\n"
            if p.allow_groups:
                output += "**Groups:**\n"
                for group in sorted(p.allow_groups):
                    output += f"  - `{group}`\n"
                output += "\n"
        else:
            output += "_Empty_\n\n"

        # Deny list
        output += "## Deny List\n\n"
        if p.deny_tools or p.deny_groups:
            if p.deny_tools:
                output += "**Tools:**\n"
                for tool in sorted(p.deny_tools):
                    output += f"  - `{tool}`\n"
                output += "\n"
            if p.deny_groups:
                output += "**Groups:**\n"
                for group in sorted(p.deny_groups):
                    output += f"  - `{group}`\n"
                output += "\n"
        else:
            output += "_Empty_\n\n"

        # Shell permissions
        output += "## Shell Permissions\n\n"
        if p.shell_allowed_commands or p.shell_denied_commands:
            if p.shell_allowed_commands:
                output += "**Allowed Commands:**\n"
                for cmd in sorted(p.shell_allowed_commands):
                    output += f"  - `{cmd}`\n"
                output += "\n"
            if p.shell_denied_commands:
                output += "**Denied Commands:**\n"
                for cmd in sorted(p.shell_denied_commands):
                    output += f"  - `{cmd}`\n"
                output += "\n"
        else:
            output += "_No shell-specific permissions configured_\n\n"

        # Show currently available tools
        output += "## Currently Available Tools\n\n"
        output += f"**Agent tools:** {len(self.agent_tools)} tools\n"
        output += f"**User tools:** {len(self.user_tools)} tools\n"

        return output

    def _is_group_name(self, name: str) -> bool:
        """Check if a name refers to a group (vs a tool name).

        Groups are identified by being capitalized (e.g., "Files", "Gmail")
        while tool names are lowercase with underscores (e.g., "read_file", "gmail_send").
        """
        # Get all known group names
        known_groups = set()
        for tool in ALL_TOOLS:
            group = get_tool_group(tool)
            if group:
                known_groups.add(group)

        # If it's in our known groups, it's definitely a group
        if name in known_groups:
            return True

        # Otherwise, use heuristic: groups are typically capitalized
        # and don't contain underscores
        if name and name[0].isupper() and "_" not in name:
            return True

        return False

    def _list_groups(self, user_interface, sandbox, user_input, *args, **kwargs):
        """List all available tool groups and their tools."""
        groups = {}
        ungrouped = []

        # Collect all tools by group
        for tool in ALL_TOOLS:
            group = get_tool_group(tool) or None
            if group:
                if group not in groups:
                    groups[group] = []
                groups[group].append(tool.__name__)
            else:
                ungrouped.append(tool.__name__)

        output = "# Available Tool Groups\n\n"
        output += (
            "Use `/permissions allow <GroupName>` to allow all tools in a group.\n\n"
        )

        # Sort groups alphabetically
        for group_name in sorted(groups.keys()):
            tool_names = sorted(groups[group_name])
            output += f"## {group_name}\n\n"
            for tool_name in tool_names:
                output += f"  - `{tool_name}`\n"
            output += "\n"

        # Show ungrouped tools if any
        if ungrouped:
            output += "## Ungrouped\n\n"
            for tool_name in sorted(ungrouped):
                output += f"  - `{tool_name}`\n"
            output += "\n"

        # Summary
        output += f"\n**Total:** {len(groups)} groups, {len(ALL_TOOLS)} tools"
        if ungrouped:
            output += f" ({len(ungrouped)} ungrouped)"
        output += "\n"

        return output

    def _refresh_tools_after_permission_change(self):
        """Re-filter tools after permission changes."""
        if self.permissions_manager:
            # Re-filter from original ALL_TOOLS
            self.agent_tools = self.permissions_manager.filter_tools(ALL_TOOLS)
            # Re-discover and filter user tools
            self.user_tools = {}
            self._discover_user_tools()
            # Note: agent_schema property will auto-refresh on next access

    def _auth_tool(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Authorize a user tool that requires authentication.

        Usage: /auth-tool <tool_name>

        This runs the tool's --authorize flag interactively, allowing the tool
        to complete any authentication flow it requires (e.g., OAuth, API keys).
        """
        from .tools.user_tools import get_tools_dir

        tool_name = user_input.strip()
        if not tool_name:
            # List tools that need authorization
            discovered = discover_tools(check_auth=True)
            unauth_tools = [
                t
                for t in discovered
                if not t.is_authorized and t.metadata.requires_auth
            ]

            if not unauth_tools:
                return "All tools are authorized. No action needed."

            output = "**Tools requiring authorization:**\n\n"
            for tool in unauth_tools:
                output += (
                    f"  • `{tool.file_stem}` - {tool.error or 'Needs authorization'}\n"
                )
            output += "\n**Usage:** `/auth-tool <tool_name>`"
            return output

        # Find the tool file
        tools_dir = get_tools_dir()
        tool_path = tools_dir / f"{tool_name}.py"

        if not tool_path.exists():
            return f"Tool not found: {tool_name}"

        # Run the tool with --authorize interactively
        user_interface.handle_system_message(
            f"Running authorization for {tool_name}...", markdown=False
        )

        try:
            # Run interactively (not capturing output)
            result = subprocess.run(
                ["uv", "run", str(tool_path), "--authorize"],
                cwd=str(tool_path.parent),
                timeout=300,  # 5 minute timeout for interactive auth
            )

            if result.returncode == 0:
                # Refresh user tools to pick up the newly authorized tool
                self.refresh_user_tools()
                return f"✓ Tool '{tool_name}' authorized successfully!\nThe tool is now available for use."
            else:
                return f"✗ Authorization failed for '{tool_name}' (exit code {result.returncode})"

        except subprocess.TimeoutExpired:
            return f"✗ Authorization timed out for '{tool_name}'"
        except Exception as e:
            return f"✗ Error during authorization: {e}"

    async def _tools(self, user_interface, sandbox, user_input, *args, **kwargs):
        """List available tools and manage user tool authorization.

        Shows an interactive tree of all built-in and user tools organized by group.
        Users can expand/collapse groups and select user tools to authorize.
        """
        from .tools.user_tools import get_tools_dir

        # Discover all user tools (with auth check)
        all_discovered = discover_tools(check_auth=True)

        # Build groups for built-in tools
        builtin_groups = {}
        for tool in self.agent_tools:
            group = get_tool_group(tool) or "Ungrouped"
            if group not in builtin_groups:
                builtin_groups[group] = []
            builtin_groups[group].append(
                {
                    "name": tool.__name__,
                    "description": (tool.__doc__ or "").split("\n")[0][:50],
                    "type": "builtin",
                }
            )

        # Sort tools within each group
        for group in builtin_groups:
            builtin_groups[group].sort(key=lambda t: t["name"])

        # Categorize user tools
        user_tools_by_status = {
            "available": [],
            "needs_auth": [],
            "error": [],
        }

        for tool in all_discovered:
            tool_info = {
                "name": tool.name,
                "file_stem": tool.file_stem,
                "description": (tool.spec.get("description", "") if tool.spec else "")[
                    :50
                ],
                "requires_auth": tool.metadata.requires_auth,
                "is_authorized": tool.is_authorized,
                "error": tool.error,
                "type": "user",
            }
            if tool.error and not tool.is_authorized and tool.metadata.requires_auth:
                user_tools_by_status["needs_auth"].append(tool_info)
            elif tool.error:
                user_tools_by_status["error"].append(tool_info)
            else:
                user_tools_by_status["available"].append(tool_info)

        # Build the interactive menu options
        options = []
        option_metadata = []  # Track what each option represents

        # Add built-in tool groups (collapsed - just show group name)
        options.append("━━━ Built-in Tools ━━━")
        option_metadata.append({"type": "header"})

        for group_name in sorted(builtin_groups.keys()):
            tools = builtin_groups[group_name]
            options.append(f"  📁 {group_name} ({len(tools)} tools)")
            option_metadata.append(
                {
                    "type": "builtin_group",
                    "group": group_name,
                    "tools": tools,
                    "expanded": False,
                }
            )

        # Add user tools section
        tools_dir = get_tools_dir()
        options.append("")
        option_metadata.append({"type": "spacer"})
        options.append(f"━━━ User Tools ({tools_dir}) ━━━")
        option_metadata.append({"type": "header"})

        # Available user tools
        if user_tools_by_status["available"]:
            for tool in sorted(
                user_tools_by_status["available"], key=lambda t: t["name"]
            ):
                auth_icon = "🔐 " if tool["requires_auth"] else ""
                options.append(f"  ✓ {auth_icon}{tool['name']}")
                option_metadata.append(
                    {"type": "user_tool", "tool": tool, "action": None}
                )

        # User tools needing authorization (these are actionable)
        if user_tools_by_status["needs_auth"]:
            for tool in sorted(
                user_tools_by_status["needs_auth"], key=lambda t: t["name"]
            ):
                options.append(f"  ⚠ {tool['file_stem']} (needs auth)")
                option_metadata.append(
                    {
                        "type": "user_tool_auth",
                        "tool": tool,
                        "action": "authorize",
                    }
                )

        # User tools with errors
        if user_tools_by_status["error"]:
            for tool in sorted(user_tools_by_status["error"], key=lambda t: t["name"]):
                options.append(f"  ✗ {tool['name']} (error)")
                option_metadata.append({"type": "user_tool_error", "tool": tool})

        if not all_discovered:
            options.append("  (no user tools)")
            option_metadata.append({"type": "empty"})

        # Add actions at the bottom
        options.append("")
        option_metadata.append({"type": "spacer"})
        options.append("━━━ Actions ━━━")
        option_metadata.append({"type": "header"})
        options.append("  📋 Show all tools (detailed list)")
        option_metadata.append({"type": "action", "action": "detailed"})
        options.append("  ❌ Close")
        option_metadata.append({"type": "action", "action": "close"})

        # Present the interactive selector
        try:
            choice_idx = await self._interactive_tools_browser(
                user_interface, options, option_metadata, builtin_groups
            )

            if choice_idx is not None and choice_idx < len(option_metadata):
                meta = option_metadata[choice_idx]

                if meta["type"] == "user_tool_auth":
                    # Authorize the selected tool
                    tool_name = meta["tool"]["file_stem"]
                    return self._auth_tool(user_interface, sandbox, tool_name)

                elif meta["type"] == "action":
                    if meta["action"] == "detailed":
                        return self._tools_detailed(
                            builtin_groups, user_tools_by_status, tools_dir
                        )

            return ""

        except (AttributeError, NotImplementedError):
            # Interactive browser not available, fall back to text output
            return self._tools_detailed(builtin_groups, user_tools_by_status, tools_dir)

    async def _interactive_tools_browser(
        self, user_interface, options, option_metadata, builtin_groups
    ):
        """Run an interactive tool browser with expand/collapse support."""
        expanded_groups = set()  # Track which groups are expanded
        current_options = list(options)
        current_metadata = list(option_metadata)

        while True:
            try:
                choice = await user_interface.get_user_choice(
                    "Tools Browser (select group to expand, or tool to act on):",
                    current_options,
                )

                if not choice:
                    return None

                # Find the index of the selected option
                try:
                    choice_idx = current_options.index(choice)
                except ValueError:
                    return None

                meta = current_metadata[choice_idx]

                # Handle group expansion/collapse
                if meta["type"] == "builtin_group":
                    group_name = meta["group"]
                    if group_name in expanded_groups:
                        # Collapse: remove this group from expanded and rebuild
                        expanded_groups.discard(group_name)
                    else:
                        # Expand: add this group to expanded
                        expanded_groups.add(group_name)

                    # Rebuild the options list with current expansion state
                    current_options, current_metadata = self._build_tools_options(
                        builtin_groups, option_metadata, expanded_groups
                    )
                    continue

                # Handle actionable items
                elif meta["type"] in ("user_tool_auth", "action"):
                    return choice_idx

                # Headers, spacers, and non-actionable items - just re-show
                else:
                    continue

            except (KeyboardInterrupt, EOFError):
                return None

    def _build_tools_options(self, builtin_groups, base_metadata, expanded_groups):
        """Rebuild options list based on which groups are expanded."""
        from .tools.user_tools import get_tools_dir

        options = []
        metadata = []

        # Header
        options.append("━━━ Built-in Tools ━━━")
        metadata.append({"type": "header"})

        # Built-in groups
        for group_name in sorted(builtin_groups.keys()):
            tools = builtin_groups[group_name]
            is_expanded = group_name in expanded_groups
            icon = "📂" if is_expanded else "📁"
            options.append(f"  {icon} {group_name} ({len(tools)} tools)")
            metadata.append(
                {
                    "type": "builtin_group",
                    "group": group_name,
                    "tools": tools,
                    "expanded": is_expanded,
                }
            )

            # If expanded, show the tools
            if is_expanded:
                for tool in tools:
                    options.append(f"      • {tool['name']}")
                    metadata.append({"type": "builtin_tool", "tool": tool})

        # Copy the rest from base_metadata (user tools section)
        # Find where user tools section starts in base_metadata
        user_section_start = None
        for i, m in enumerate(base_metadata):
            if m["type"] == "header" and i > 0:
                # Found the user tools header
                user_section_start = i - 1  # Include the spacer before it
                break

        if user_section_start is not None:
            # Find corresponding options
            opt_idx = 0
            for i, m in enumerate(base_metadata):
                if i >= user_section_start:
                    # Map base_metadata index to options index
                    # This is tricky - we need to find where in options this corresponds
                    break
                if m["type"] == "builtin_group":
                    opt_idx += 1
                elif m["type"] in ("header", "spacer"):
                    opt_idx += 1

            # Simpler approach: just append everything after built-in section
            for m in base_metadata:
                if m["type"] == "spacer" and len(metadata) > 2:
                    # We've passed built-in tools, start copying
                    break

            # Add user tools section (from original)
            all_discovered = discover_tools(check_auth=True)
            tools_dir = get_tools_dir()

            options.append("")
            metadata.append({"type": "spacer"})
            options.append(f"━━━ User Tools ({tools_dir}) ━━━")
            metadata.append({"type": "header"})

            for tool in all_discovered:
                if (
                    tool.error
                    and not tool.is_authorized
                    and tool.metadata.requires_auth
                ):
                    options.append(f"  ⚠ {tool.file_stem} (needs auth)")
                    metadata.append(
                        {
                            "type": "user_tool_auth",
                            "tool": {"file_stem": tool.file_stem, "name": tool.name},
                            "action": "authorize",
                        }
                    )
                elif tool.error:
                    options.append(f"  ✗ {tool.name} (error)")
                    metadata.append(
                        {"type": "user_tool_error", "tool": {"name": tool.name}}
                    )
                else:
                    auth_icon = "🔐 " if tool.metadata.requires_auth else ""
                    options.append(f"  ✓ {auth_icon}{tool.name}")
                    metadata.append(
                        {
                            "type": "user_tool",
                            "tool": {"name": tool.name},
                            "action": None,
                        }
                    )

            if not all_discovered:
                options.append("  (no user tools)")
                metadata.append({"type": "empty"})

            # Actions
            options.append("")
            metadata.append({"type": "spacer"})
            options.append("━━━ Actions ━━━")
            metadata.append({"type": "header"})
            options.append("  📋 Show all tools (detailed list)")
            metadata.append({"type": "action", "action": "detailed"})
            options.append("  ❌ Close")
            metadata.append({"type": "action", "action": "close"})

        return options, metadata

    def _tools_detailed(self, builtin_groups, user_tools_by_status, tools_dir):
        """Generate detailed text output of all tools."""
        output = "# Available Tools (Detailed)\n\n"

        # Built-in tools
        output += "## Built-in Tools\n\n"
        for group_name in sorted(builtin_groups.keys()):
            tools = builtin_groups[group_name]
            output += f"### {group_name}\n\n"
            for tool in tools:
                output += f"  • `{tool['name']}` - {tool['description']}\n"
            output += "\n"

        output += f"_Total: {sum(len(t) for t in builtin_groups.values())} built-in tools_\n\n"

        # User tools
        output += "## User Tools\n\n"
        output += f"_Directory: `{tools_dir}`_\n\n"

        if user_tools_by_status["available"]:
            output += "### ✓ Available\n\n"
            for tool in sorted(
                user_tools_by_status["available"], key=lambda t: t["name"]
            ):
                auth_note = " 🔐" if tool["requires_auth"] else ""
                output += f"  • `{tool['name']}`{auth_note} - {tool['description']}\n"
            output += "\n"

        if user_tools_by_status["needs_auth"]:
            output += "### ⚠ Needs Authorization\n\n"
            for tool in sorted(
                user_tools_by_status["needs_auth"], key=lambda t: t["name"]
            ):
                output += f"  • `{tool['file_stem']}` - {tool['error'] or 'Requires authorization'}\n"
            output += "\n"

        if user_tools_by_status["error"]:
            output += "### ✗ Errors\n\n"
            for tool in sorted(user_tools_by_status["error"], key=lambda t: t["name"]):
                output += f"  • `{tool['name']}` - {tool['error']}\n"
            output += "\n"

        total = sum(len(v) for v in user_tools_by_status.values())
        if total == 0:
            output += "_No user tools found._\n\n"
        else:
            output += f"_Total: {total} user tools_\n\n"

        return output

    async def _plan(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Enter plan mode or manage plans.

        Usage:
            /plan                    - Start planning dialogue (prompts for topic)
            /plan <topic>            - Start planning dialogue with topic
            /plan list               - List active plans (human-only)
            /plan view <id>          - View a specific plan (human-only)
            /plan approve <id>       - Approve a plan for execution (human-only)
            /plan abandon <id>       - Abandon/archive a plan (human-only)

        When starting a plan (no subcommand), this injects a planning request into
        the conversation and the agent will enter plan mode to collaborate with you.
        """
        from pathlib import Path
        from silica.developer.plans import PlanManager, PlanStatus

        def _print(msg, markdown=True):
            """Print directly to user without adding to conversation."""
            user_interface.handle_system_message(msg, markdown=markdown)

        # Get plan manager and project root
        if self.context.history_base_dir is None:
            base_dir = Path.home() / ".silica" / "personas" / "default"
        else:
            base_dir = Path(self.context.history_base_dir)
        plan_manager = PlanManager(base_dir)

        # Get project root for filtering plans
        if (
            hasattr(self.context, "sandbox")
            and self.context.sandbox is not None
            and hasattr(self.context.sandbox, "root_directory")
        ):
            root_dir = str(self.context.sandbox.root_directory)
        else:
            root_dir = os.getcwd()

        # Note: chat_history is available via kwargs.get("chat_history", [])
        # if needed for future enhancements

        args_list = user_input.strip().split(maxsplit=1) if user_input.strip() else []

        # Determine if this is a subcommand or a planning request
        subcommands = ["list", "view", "approve", "abandon", "new"]
        command = args_list[0].lower() if args_list else ""

        # Context-aware /plan (no args): view active plan or create new
        if not command:
            # Check for session-specific active plan first
            active_plan_id = self.context.active_plan_id
            if active_plan_id:
                plan = plan_manager.get_plan(active_plan_id)
                if plan and plan.status not in (
                    PlanStatus.COMPLETED,
                    PlanStatus.ABANDONED,
                ):
                    _print(f"Viewing active plan `{active_plan_id}`...")
                    _print(plan.to_markdown())
                    return ""
                # Clear stale reference
                self.context.active_plan_id = None

            # Fallback to most recent plan for this project
            active_plans = plan_manager.list_active_plans(root_dir=root_dir)
            if active_plans:
                plan = active_plans[0]
                _print(f"Viewing active plan `{plan.id}`...")
                _print(plan.to_markdown())
                return ""

            # No active plan - equivalent to /plan new
            command = "new"
            args_list = ["new"]

        # Check for management subcommands (human-only, no agent involvement)
        if command == "list":
            plans = plan_manager.list_active_plans(root_dir=root_dir)
            if not plans:
                _print("No active plans for this project.")
                return ""

            output = "## Active Plans\n\n"
            for plan in plans:
                output += f"- `{plan.id}` - **{plan.title}** ({plan.status.value})\n"
                output += f"  Updated: {plan.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
            _print(output)
            return ""

        elif command == "view":
            if len(args_list) < 2:
                # Use active plan if available, otherwise show picker
                active_plans = plan_manager.list_active_plans(root_dir=root_dir)
                if not active_plans:
                    _print("No plans to view for this project.")
                    return ""

                # Default to the most recent active plan
                plan_id = active_plans[0].id
                _print(f"Viewing active plan `{plan_id}`...")
            else:
                plan_id = args_list[1]

            plan = plan_manager.get_plan(plan_id)
            if not plan:
                _print(f"Plan {plan_id} not found.")
                return ""
            _print(plan.to_markdown())
            return ""

        elif command == "approve":
            if len(args_list) < 2:
                # Use active plan if it's in review, otherwise show picker
                active_plans = plan_manager.list_active_plans(root_dir=root_dir)
                plans_in_review = [
                    p for p in active_plans if p.status == PlanStatus.IN_REVIEW
                ]

                if not plans_in_review:
                    # Check if there's an active plan not in review
                    if active_plans:
                        _print(
                            f"Active plan `{active_plans[0].id}` is in {active_plans[0].status.value} status, not IN_REVIEW."
                        )
                    else:
                        _print("No plans awaiting approval for this project.")
                    return ""

                # Default to the most recent plan in review
                plan_id = plans_in_review[0].id
                _print(f"Approving plan `{plan_id}`...")
            else:
                plan_id = args_list[1]

            if plan_manager.approve_plan(plan_id):
                # Get the plan details for the execution prompt
                plan = plan_manager.get_plan(plan_id)
                _print(f"✅ Plan `{plan_id}` approved! Starting execution...")

                # Set this as the active plan for this session
                self.context.active_plan_id = plan_id

                # Build execution prompt to trigger agent
                execution_prompt = f"""The plan "{plan.title}" (ID: {plan_id}) has been approved.

Please use `exit_plan_mode("{plan_id}", "execute")` to begin execution, then work through each task:

"""
                if plan.tasks:
                    for task in plan.tasks:
                        status = "✅" if task.completed else "⬜"
                        execution_prompt += (
                            f"- {status} `{task.id}`: {task.description}\n"
                        )
                        if task.files:
                            execution_prompt += f"  Files: {', '.join(task.files)}\n"

                execution_prompt += """
After completing each task, call `complete_plan_task(plan_id, task_id)`.
When all tasks are done, call `complete_plan(plan_id)`."""

                # Return prompt with auto_add=True to trigger agent execution
                return (execution_prompt, True)
            else:
                plan = plan_manager.get_plan(plan_id)
                if not plan:
                    _print(f"Plan {plan_id} not found.")
                else:
                    _print(
                        f"Cannot approve plan in {plan.status.value} status. Must be IN_REVIEW."
                    )
            return ""

        elif command == "abandon":
            if len(args_list) < 2:
                # Use active plan if available, otherwise show picker
                active_plans = plan_manager.list_active_plans(root_dir=root_dir)
                if not active_plans:
                    _print("No active plans to abandon for this project.")
                    return ""

                # Default to the most recent active plan
                plan_id = active_plans[0].id
                plan = active_plans[0]
                _print(f"Abandoning active plan `{plan_id}` ({plan.title})...")
            else:
                plan_id = args_list[1]

            if plan_manager.abandon_plan(plan_id):
                # Clear active plan if this was it
                if self.context.active_plan_id == plan_id:
                    self.context.active_plan_id = None
                _print(f"🗑️ Plan `{plan_id}` abandoned and archived.")
            else:
                _print(f"Could not abandon plan {plan_id}.")
            return ""

        elif command == "new" or command not in subcommands:
            # /plan new or /plan <topic> - create a new plan with agent

            # Get topic (either from args or prompt user)
            if command == "new":
                # /plan new or /plan new <topic>
                if len(args_list) > 1:
                    topic = args_list[1]
                else:
                    topic = await user_interface.get_user_input(
                        "What would you like to plan? "
                    )
                    if not topic.strip():
                        _print("Cancelled - no topic provided.")
                        return ""
                    topic = topic.strip()
            else:
                # /plan <topic> (backwards compatible)
                topic = user_input.strip()

            _print(
                f"📋 **Entering Plan Mode**\n\nTopic: {topic}\n\nThe agent will now help you create a structured plan..."
            )

            # Create the planning prompt to send to agent
            planning_prompt = f"""I'd like to enter plan mode to work on: {topic}

Please use the `enter_plan_mode` tool to start planning this. Then:
1. Analyze what's needed for this task
2. Ask me clarifying questions using `ask_clarifications` if anything is unclear
3. Document the implementation approach using `update_plan`
4. Break down the work into tasks using `add_plan_tasks`

Let's collaborate on creating a solid plan before implementation."""

            # Return (content, auto_add=True) to automatically add to conversation
            # and trigger agent response
            return (planning_prompt, True)

    def _discover_user_tools(self):
        """Discover user-created tools from ~/.silica/tools/."""
        try:
            # Check auth during schema building - unauthenticated tools won't be available
            # Skip auth check if requested (e.g., during CLI tool registration)
            discovered = discover_tools(check_auth=not self._skip_user_tool_auth)
            for tool in discovered:
                if tool.error and not tool.is_authorized:
                    # Tool requires auth but isn't authorized - log but don't add to toolbox
                    # Only show warning if show_warnings is enabled (avoids duplicate messages)
                    if self._show_warnings:
                        self.context.user_interface.handle_system_message(
                            f"Warning: User tool '{tool.name}' requires authorization. "
                            f"Use /auth-tool {tool.file_stem} to authorize.",
                            markdown=False,
                        )
                elif tool.error:
                    # Other errors - log but tool won't be available
                    if self._show_warnings:
                        self.context.user_interface.handle_system_message(
                            f"Warning: User tool '{tool.name}' failed to load: {tool.error}",
                            markdown=False,
                        )
                elif tool.spec and tool.is_authorized:
                    # Only add tools that are authorized and have a valid spec
                    self.user_tools[tool.name] = tool

            # Filter user tools based on permissions
            if self.permissions_manager:
                self.user_tools = self.permissions_manager.filter_user_tools(
                    self.user_tools
                )
        except Exception as e:
            # Don't fail if user tool discovery fails
            if self._show_warnings:
                self.context.user_interface.handle_system_message(
                    f"Warning: Failed to discover user tools: {e}",
                    markdown=False,
                )

    def refresh_user_tools(self):
        """Re-discover user tools (call after creating/modifying tools)."""
        self.user_tools.clear()
        self._discover_user_tools()

    @property
    def agent_schema(self) -> List[dict]:
        """Dynamically generate schemas, re-discovering user tools each time.

        This ensures newly created user tools are immediately available
        without requiring a session restart.
        """
        # Re-discover user tools to pick up any newly created ones
        # Use show_warnings=False to avoid duplicate warnings on every API call
        old_show_warnings = self._show_warnings
        self._show_warnings = False
        try:
            # Clear and re-discover to pick up new tools
            self.user_tools.clear()
            self._discover_user_tools()
        finally:
            self._show_warnings = old_show_warnings

        return self.schemas()

    def schemas(self, enable_caching: bool = True) -> List[dict]:
        """Generate schemas for all tools in the toolbox.

        Returns a list of schema dictionaries matching the format of TOOLS_SCHEMA.
        Each schema has name, description, and input_schema with properties and required fields.
        Includes both built-in tools and user-created tools.

        User tools take precedence over built-in tools with the same name, ensuring
        no duplicates in the final schema list.
        """
        schemas = []

        # Collect user tool names first (they take precedence)
        user_tool_names = set(self.user_tools.keys())

        # Built-in tools (skip if user tool with same name exists)
        for tool in self.agent_tools:
            if hasattr(tool, "schema"):
                schema = tool.schema()
                tool_name = schema.get("name", tool.__name__)
                # Skip built-in tools that have user tool replacements
                if tool_name not in user_tool_names:
                    schemas.append(schema)

        # User-created tools (always included, they take precedence)
        for name, tool in self.user_tools.items():
            if tool.spec:
                schemas.append(tool.spec)

        if schemas and enable_caching:
            schemas[-1]["cache_control"] = {"type": "ephemeral"}
        return schemas
