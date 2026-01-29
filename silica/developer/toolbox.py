import json
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, List, Dict

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

if TYPE_CHECKING:
    from .mcp.manager import MCPToolManager


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
        mcp_manager: "MCPToolManager | None" = None,
    ):
        self.context = context
        self.local = {}  # CLI tools
        self.mcp_manager: "MCPToolManager | None" = mcp_manager

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
        self.register_cli_tool(
            "compact-rollback",
            self._compact_rollback,
            "Rollback to the conversation state before the last compaction",
        )
        self.register_cli_tool(
            "repair-history",
            self._repair_history,
            "Repair chat history by truncating oversized tool results",
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

        # Register MCP management CLI tool
        self.register_cli_tool(
            "mcp",
            self._mcp,
            "Manage MCP server connections and tools",
        )

        # Register Island management CLI tool
        self.register_cli_tool(
            "island",
            self._island,
            "Manage Agent Island connection",
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

            # Check if this is an MCP tool (prefixed with mcp_)
            if self.mcp_manager and self.mcp_manager.is_mcp_tool(tool_name):
                return await self._invoke_mcp_tool(tool_use)

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
            # Try to parse JSON output and check for image data
            try:
                parsed = json.loads(result.output)
                content = self._process_user_tool_result(parsed)
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

    async def _invoke_mcp_tool(self, tool_use) -> dict:
        """Invoke an MCP server tool.

        Routes the tool call to the appropriate MCP server based on
        the tool name prefix.
        """
        tool_name = tool_use.name
        tool_use_id = getattr(tool_use, "id", "unknown_id")
        args = tool_use.input or {}

        if not self.mcp_manager:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": "MCP manager not available",
            }

        try:
            result = await self.mcp_manager.call_tool(tool_name, args)

            # Format the result as a string if it isn't already
            if isinstance(result, str):
                content = result
            elif isinstance(result, list):
                content = "\n".join(str(item) for item in result)
            elif result is None:
                content = "Tool completed successfully (no output)"
            else:
                content = json.dumps(result, indent=2, default=str)

            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
            }

        except Exception as e:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": f"MCP tool error: {e}",
            }

    def _process_user_tool_result(self, parsed: dict) -> list | str:
        """Process a parsed JSON result from a user tool.

        Detects image data in the response and converts it to proper
        Anthropic API image content blocks. This prevents base64 image
        data from being tokenized as text (which would explode context).

        Supported patterns:
        1. {"base64": "...", "media_type": "image/png"} - explicit media type
        2. {"base64": "..."} - auto-detect media type from data
        3. {"image": {"base64": "...", "media_type": "..."}} - nested image object

        Args:
            parsed: The parsed JSON response from the tool

        Returns:
            Either a list of content blocks (if images found) or a JSON string
        """
        # Check for image data in the response
        image_data = None
        media_type = None
        text_content = {}

        # Pattern 1 & 2: Top-level base64 field
        if "base64" in parsed and isinstance(parsed["base64"], str):
            image_data = parsed["base64"]
            media_type = parsed.get("media_type")

            # Build text content from other fields
            for key, value in parsed.items():
                if key not in ("base64", "media_type"):
                    text_content[key] = value

        # Pattern 3: Nested image object
        elif "image" in parsed and isinstance(parsed["image"], dict):
            img_obj = parsed["image"]
            if "base64" in img_obj:
                image_data = img_obj["base64"]
                media_type = img_obj.get("media_type")

            # Build text content from other fields
            for key, value in parsed.items():
                if key != "image":
                    text_content[key] = value

        # If no image data found, return formatted JSON string
        if not image_data:
            return json.dumps(parsed, indent=2)

        # Auto-detect media type if not provided
        if not media_type:
            media_type = self._detect_image_media_type(image_data)

        # Build the content blocks
        content_blocks = []

        # Add text content if there are other fields
        if text_content:
            content_blocks.append(
                {
                    "type": "text",
                    "text": json.dumps(text_content, indent=2),
                }
            )

        # Add the image content block
        content_blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_data,
                },
            }
        )

        return content_blocks

    def _detect_image_media_type(self, base64_data: str) -> str:
        """Detect the media type of a base64-encoded image.

        Examines the first few bytes of the decoded data to identify
        the image format based on magic bytes.

        Args:
            base64_data: Base64-encoded image data

        Returns:
            Media type string (defaults to "image/png" if unknown)
        """
        import base64

        try:
            # Decode just enough to check magic bytes
            # Most image formats can be identified from first 12 bytes
            decoded = base64.b64decode(base64_data[:24])

            # PNG: 89 50 4E 47 0D 0A 1A 0A
            if decoded.startswith(b"\x89PNG\r\n\x1a\n"):
                return "image/png"

            # JPEG: FF D8 FF
            if decoded.startswith(b"\xff\xd8\xff"):
                return "image/jpeg"

            # GIF: 47 49 46 38 (GIF8)
            if decoded.startswith(b"GIF8"):
                return "image/gif"

            # WebP: 52 49 46 46 ... 57 45 42 50 (RIFF...WEBP)
            if decoded.startswith(b"RIFF") and b"WEBP" in decoded[:12]:
                return "image/webp"

        except Exception:
            pass

        # Default to PNG if we can't detect
        return "image/png"

    async def invoke_agent_tools(self, tool_uses):
        """Invoke multiple agent tools, potentially in parallel."""
        import asyncio
        from .sandbox import DoSomethingElseError

        # Log tool usage for user feedback
        for tool_use in tool_uses:
            tool_name = getattr(tool_use, "name", "unknown_tool")
            tool_use_id = getattr(tool_use, "id", None)
            tool_input = getattr(tool_use, "input", {})
            self.context.user_interface.handle_tool_use(
                tool_name, tool_input, tool_use_id=tool_use_id
            )

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
        help_text += "- **/compact-rollback** - Rollback to conversation state before the last compaction\n"

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
* Use `/compact-rollback` to restore the conversation from before the last compaction
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
        from .agent_loop import _process_file_mentions

        content = "[bold cyan]System Message:[/bold cyan]\n\n"
        content += json.dumps(create_system_message(self.context), indent=2)
        content += "\n\n[bold cyan]Tool Specifications:[/bold cyan]\n"
        content += json.dumps(self.agent_schema, indent=2)
        content += (
            "\n\n[bold cyan]Chat History (with inlined file contents):[/bold cyan]\n"
        )
        inlined_history = _process_file_mentions(kwargs["chat_history"])
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

        # Get git branch name
        branch_name = None
        try:
            import subprocess

            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                branch_name = result.stdout.strip()
        except Exception:
            pass

        # Format the output
        info = "# Session Information\n\n"

        # Persona
        info += f"**Persona:** `{persona_name}`\n\n"

        # Git branch
        if branch_name:
            info += f"**Git Branch:** `{branch_name}`\n\n"

        # Session IDs
        info += f"**Session ID:** `{session_id}`\n\n"
        if parent_session_id:
            info += f"**Parent Session ID:** `{parent_session_id}`\n\n"

        # Session file path
        info += f"**Session File:** `{history_file}`\n\n"

        # Current working directory
        import os

        cwd = os.getcwd()
        info += f"**Current Directory:** `{cwd}`\n\n"

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

        # Print directly instead of returning, so we don't get prompted to add to conversation
        user_interface.handle_system_message(info, markdown=True)
        return ("", False)

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

    def _compact_rollback(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Rollback to the conversation state before the last compaction.

        This restores the chat history from the most recent pre-compaction archive.
        """
        import json

        try:
            # Get the history directory for this session
            history_dir = self.context._get_history_dir()

            # Find all pre-compaction archives
            archives = sorted(
                history_dir.glob("pre-compaction-*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,  # Most recent first
            )

            if not archives:
                return "No compaction archives found. Nothing to rollback to."

            # Get the most recent archive
            latest_archive = archives[0]

            # Load the archived conversation
            with open(latest_archive, "r") as f:
                archived_data = json.load(f)

            # Extract chat history from archive (key is "messages" in the archive format)
            if "messages" in archived_data:
                archived_history = archived_data["messages"]
            elif "chat_history" in archived_data:
                archived_history = archived_data["chat_history"]
            else:
                return f"Error: Archive {latest_archive.name} has no messages or chat_history"
            archived_count = len(archived_history)
            current_count = len(self.context.chat_history)

            # Restore the chat history
            self.context._chat_history = archived_history
            self.context._tool_result_buffer.clear()

            # Flush to save the restored state
            self.context.flush(self.context.chat_history, compact=False)

            # Optionally remove the used archive (or keep for multiple rollbacks)
            # For now, we'll keep it so users can rollback multiple times if needed

            result = "✓ Conversation rolled back successfully!\n\n"
            result += f"**Restored from:** {latest_archive.name}\n\n"
            result += f"**Messages:** {current_count} → {archived_count}\n\n"
            if len(archives) > 1:
                result += f"**Note:** {len(archives) - 1} older archive(s) still available\n\n"

            return result

        except Exception as e:
            import traceback

            error_details = traceback.format_exc()
            user_interface.handle_system_message(
                f"Rollback failed: {e}\n\n{error_details}", markdown=False
            )
            return f"Error: Rollback failed - {e}"

    def _repair_history(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Repair chat history by truncating oversized tool results.

        This command scans the conversation history for tool_result blocks that
        exceed the token limit and replaces them with truncation messages. This
        can recover a session that became unloadable due to context overflow.

        Usage:
            /repair-history           - Scan and fix with default limit (50K tokens)
            /repair-history 20000     - Use custom token limit
            /repair-history --dry-run - Show what would be fixed without changing anything
        """
        from silica.developer.tool_result_limit import (
            get_result_content_size,
            create_truncation_message,
            get_max_tool_result_tokens,
        )

        # Parse arguments
        args_list = user_input.strip().split() if user_input.strip() else []
        dry_run = "--dry-run" in args_list
        args_list = [a for a in args_list if a != "--dry-run"]

        # Get token limit
        if args_list:
            try:
                max_tokens = int(args_list[0])
            except ValueError:
                return f"Error: Invalid token limit '{args_list[0]}'. Use a number like 50000."
        else:
            max_tokens = get_max_tool_result_tokens()

        # Scan history for oversized tool results
        oversized = []
        total_messages = len(self.context.chat_history)

        for msg_idx, message in enumerate(self.context.chat_history):
            if message.get("role") != "user":
                continue

            content = message.get("content", [])
            if not isinstance(content, list):
                continue

            for block_idx, block in enumerate(content):
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_result":
                    continue

                # Check size of this tool result
                result_for_check = {"content": block.get("content", "")}
                estimated_tokens, content_type = get_result_content_size(
                    result_for_check
                )

                if estimated_tokens > max_tokens:
                    tool_use_id = block.get("tool_use_id", "unknown")
                    oversized.append(
                        {
                            "msg_idx": msg_idx,
                            "block_idx": block_idx,
                            "tool_use_id": tool_use_id,
                            "estimated_tokens": estimated_tokens,
                            "content_type": content_type,
                        }
                    )

        if not oversized:
            return f"✓ No oversized tool results found (checked {total_messages} messages, limit: {max_tokens:,} tokens)"

        # Report findings
        result = f"Found {len(oversized)} oversized tool result(s):\n\n"
        for item in oversized:
            result += f"- Message {item['msg_idx']}: ~{item['estimated_tokens']:,} tokens ({item['content_type']})\n"
        result += "\n"

        if dry_run:
            result += "**Dry run** - no changes made. Run `/repair-history` to fix."
            user_interface.handle_system_message(result, markdown=True)
            return ("", False)

        # Fix the oversized results
        fixed_count = 0
        for item in oversized:
            msg_idx = item["msg_idx"]
            block_idx = item["block_idx"]

            # Get the block
            block = self.context.chat_history[msg_idx]["content"][block_idx]

            # Create truncation message
            truncation_msg = create_truncation_message(
                tool_name="unknown",  # We don't have the tool name in tool_result
                original_tokens=item["estimated_tokens"],
                max_tokens=max_tokens,
                content_type=item["content_type"],
            )

            # Replace the content but preserve tool_use_id and type
            block["content"] = truncation_msg
            block["is_error"] = True
            fixed_count += 1

        # Save the repaired history
        self.context.flush(self.context.chat_history, compact=False)

        result += f"✓ Fixed {fixed_count} oversized tool result(s)\n\n"
        result += "History has been saved. The session should now be recoverable."

        user_interface.handle_system_message(result, markdown=True)
        return ("", False)

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
            "schema_invalid": [],  # Tools with invalid schemas (won't be sent to API)
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
                "schema_valid": tool.schema_valid,
                "schema_errors": tool.schema_errors,
                "type": "user",
            }
            if tool.error and not tool.is_authorized and tool.metadata.requires_auth:
                user_tools_by_status["needs_auth"].append(tool_info)
            elif not tool.schema_valid:
                # Schema invalid - separate category for clarity
                user_tools_by_status["schema_invalid"].append(tool_info)
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

        # User tools with invalid schemas (won't be sent to API)
        if user_tools_by_status["schema_invalid"]:
            for tool in sorted(
                user_tools_by_status["schema_invalid"], key=lambda t: t["name"]
            ):
                options.append(f"  ✗ {tool['name']} (invalid schema)")
                option_metadata.append(
                    {"type": "user_tool_schema_invalid", "tool": tool}
                )

        # User tools with other errors
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
                elif not tool.schema_valid:
                    options.append(f"  ✗ {tool.name} (invalid schema)")
                    metadata.append(
                        {
                            "type": "user_tool_schema_invalid",
                            "tool": {
                                "name": tool.name,
                                "schema_errors": tool.schema_errors,
                            },
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

        if user_tools_by_status["schema_invalid"]:
            output += "### ✗ Invalid Schema (excluded from API)\n\n"
            for tool in sorted(
                user_tools_by_status["schema_invalid"], key=lambda t: t["name"]
            ):
                output += f"  • `{tool['name']}`\n"
                # Show schema errors for debugging
                for err in tool.get("schema_errors", []):
                    output += f"      - {err}\n"
            output += "\n"

        if user_tools_by_status["error"]:
            output += "### ✗ Other Errors\n\n"
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
            /plan                      - View active plan or start new
            /plan <topic>              - Start planning with topic
            /plan new [--local|--global] <topic>  - Create new plan
            /plan list                 - List active plans
            /plan view [id]            - View plan details
            /plan approve [id] [--shelve]  - Approve plan for execution
            /plan approve [id] --push [workspace]  - Approve and push to remote
            /plan reject [id] [feedback]   - Reject and request revisions
            /plan abandon [id]         - Abandon/archive plan
            /plan reopen [id]          - Reopen completed/abandoned plan
            /plan move <id> [--local|--global]  - Move plan storage
            /plan push [id] [--local=PORT]  - Push to remote workspace
            /plan push --all           - Push all shelved plans
            /plan status [--remote]    - View plan execution status

        Workflow:
            1. /plan <topic> - Agent creates plan, asks questions, adds tasks
            2. Agent calls submit_for_approval() - Plan shown to user
            3. /plan approve - User approves, agent executes
               OR /plan reject <feedback> - Agent revises plan
        """
        from pathlib import Path
        from silica.developer.plans import (
            PlanManager,
            PlanStatus,
            get_git_root,
            LOCATION_LOCAL,
            LOCATION_GLOBAL,
        )

        def _print(msg, markdown=True):
            """Print directly to user without adding to conversation."""
            user_interface.handle_system_message(msg, markdown=markdown)

        # Get persona base dir
        if self.context.history_base_dir is None:
            base_dir = Path.home() / ".silica" / "personas" / "default"
        else:
            base_dir = Path(self.context.history_base_dir)

        # Get project root for filtering and storage location
        if (
            hasattr(self.context, "sandbox")
            and self.context.sandbox is not None
            and hasattr(self.context.sandbox, "root_directory")
        ):
            root_dir = str(self.context.sandbox.root_directory)
            project_root = get_git_root(root_dir)
        else:
            root_dir = os.getcwd()
            project_root = get_git_root(root_dir)

        # Create plan manager with both global and local support
        plan_manager = PlanManager(base_dir, project_root=project_root)

        def _location_emoji(location: str) -> str:
            """Get emoji for storage location."""
            return "📁" if location == LOCATION_LOCAL else "🌐"

        # Note: chat_history is available via kwargs.get("chat_history", [])
        # if needed for future enhancements

        args_list = user_input.strip().split(maxsplit=1) if user_input.strip() else []

        # Determine if this is a subcommand or a planning request
        subcommands = [
            "list",
            "view",
            "approve",
            "reject",
            "abandon",
            "reopen",
            "new",
            "move",
            "push",
            "status",
        ]
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
            output += "_📁 = local, 🌐 = global_\n\n"
            for plan in plans:
                loc = _location_emoji(plan.storage_location)
                output += (
                    f"- {loc} `{plan.id}` - **{plan.title}** ({plan.status.value})\n"
                )
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
            # Parse flags
            shelve = False
            push_workspace = None  # None = no push, "" = push with default name
            plan_id = None
            if len(args_list) >= 2:
                args_parts = args_list[1].split()
                i = 0
                while i < len(args_parts):
                    arg = args_parts[i]
                    if arg == "--shelve":
                        shelve = True
                    elif arg == "--push":
                        # Check if next arg is workspace name (not another flag)
                        if i + 1 < len(args_parts) and not args_parts[i + 1].startswith(
                            "-"
                        ):
                            push_workspace = args_parts[i + 1]
                            i += 1
                        else:
                            push_workspace = ""  # Use default (slug-based) name
                    elif arg.startswith("--push="):
                        push_workspace = arg.split("=", 1)[1]
                    elif not plan_id and not arg.startswith("-"):
                        plan_id = arg
                    i += 1

            if not plan_id:
                # Use active plan if it's in review, otherwise show picker
                active_plans = plan_manager.list_active_plans(root_dir=root_dir)
                plans_in_review = [
                    p for p in active_plans if p.status == PlanStatus.IN_REVIEW
                ]

                if not plans_in_review:
                    if active_plans:
                        _print(
                            f"Active plan `{active_plans[0].id}` is in {active_plans[0].status.value} status, not IN_REVIEW."
                        )
                    else:
                        _print("No plans awaiting approval for this project.")
                    return ""

                plan_id = plans_in_review[0].id
                _print(f"Approving plan `{plan_id}`...")

            # If --push is specified, we approve (not shelved) and then push
            # The push will transition to IN_PROGRESS with remote tracking
            if push_workspace is not None:
                shelve = False  # --push overrides --shelve

            if plan_manager.approve_plan(plan_id, shelve=shelve):
                plan = plan_manager.get_plan(plan_id)

                if push_workspace is not None:
                    # Approve and push to remote workspace
                    _print(f"✅ Plan `{plan_id}` approved! Pushing to remote...")

                    # Determine workspace name
                    if push_workspace == "":
                        # Use plan slug as default workspace name
                        ws_name = f"plan-{plan.get_slug()}"
                    else:
                        ws_name = push_workspace

                    # Recursively call /plan push with the workspace name
                    # Build the push command args
                    push_args = f"{plan_id} --workspace={ws_name}"
                    # Store original args and call push handler
                    return await self._plan(
                        user_interface,
                        sandbox,
                        f"push {push_args}",
                        *args,
                        **kwargs,
                    )

                if shelve:
                    # Shelved - don't trigger execution, just confirm
                    _print(f"✅ Plan `{plan_id}` approved and shelved.")
                    _print(
                        f"Use `/plan push {plan_id}` to execute on a remote workspace."
                    )
                    return ""

                # Not shelved - trigger immediate execution
                _print(f"✅ Plan `{plan_id}` approved! Starting execution...")
                self.context.active_plan_id = plan_id

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

        elif command == "reject":
            # /plan reject [plan-id] [feedback]
            # Reject a plan and send it back to DRAFT with feedback
            plan_id = None
            feedback = ""

            if len(args_list) >= 2:
                parts = args_list[1].split(maxsplit=1)
                # Check if first part looks like a plan ID (short alphanumeric)
                if parts[0] and len(parts[0]) <= 10 and parts[0].isalnum():
                    plan_id = parts[0]
                    feedback = parts[1] if len(parts) > 1 else ""
                else:
                    # Entire thing is feedback
                    feedback = args_list[1]

            if not plan_id:
                # Use most recent plan in review
                active_plans = plan_manager.list_active_plans(root_dir=root_dir)
                plans_in_review = [
                    p for p in active_plans if p.status == PlanStatus.IN_REVIEW
                ]
                if not plans_in_review:
                    _print("No plans awaiting approval to reject.")
                    return ""
                plan_id = plans_in_review[0].id

            plan = plan_manager.get_plan(plan_id)
            if not plan:
                _print(f"Plan `{plan_id}` not found.")
                return ""

            if plan.status != PlanStatus.IN_REVIEW:
                _print(
                    f"Plan `{plan_id}` is in {plan.status.value} status, not IN_REVIEW."
                )
                return ""

            # Revert to DRAFT
            plan.status = PlanStatus.DRAFT
            if feedback:
                plan.add_progress(f"Plan rejected with feedback: {feedback}")
            else:
                plan.add_progress("Plan rejected - revisions requested")
            plan_manager.update_plan(plan)

            _print(f"↩️ Plan `{plan_id}` returned to draft for revisions.")

            # Build prompt for agent to revise
            revision_prompt = f"""Plan "{plan.title}" (ID: {plan_id}) was rejected and needs revisions.

"""
            if feedback:
                revision_prompt += f"""**Feedback from reviewer:**
{feedback}

"""
            revision_prompt += """Please:
1. Read the current plan with `read_plan("{plan_id}")`
2. Address the feedback by updating the approach or tasks
3. When ready, submit again with `submit_for_approval("{plan_id}")`
"""

            return (revision_prompt, True)

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

        elif command == "reopen":
            # /plan reopen [plan-id]
            # Reopen a completed or abandoned plan
            plan_id = None
            if len(args_list) >= 2:
                plan_id = args_list[1].strip()

            if not plan_id:
                # Show interactive selector for completed/abandoned plans
                completed_plans = plan_manager.list_completed_plans(
                    limit=20, root_dir=root_dir
                )
                if not completed_plans:
                    _print(
                        "No completed or abandoned plans to reopen for this project."
                    )
                    return ""

                # Build options for selector
                options = []
                for plan in completed_plans:
                    loc = _location_emoji(plan.storage_location)
                    status_str = (
                        "completed"
                        if plan.status == PlanStatus.COMPLETED
                        else "abandoned"
                    )
                    options.append(f"{loc} {plan.id} - {plan.title} ({status_str})")

                # Use interactive selector
                result = await user_interface.get_user_choice(
                    "Select a plan to reopen:", options
                )

                if result == "cancelled" or not result:
                    _print("Cancelled.")
                    return ""

                # Extract plan ID from selection
                for i, option in enumerate(options):
                    if result == option:
                        plan_id = completed_plans[i].id
                        break

                if not plan_id:
                    # User typed something - try to use it as plan ID
                    plan_id = result.split()[0] if result else None

            if not plan_id:
                _print("No plan selected.")
                return ""

            plan = plan_manager.get_plan(plan_id)
            if not plan:
                _print(f"Plan `{plan_id}` not found.")
                return ""

            if plan.status not in (PlanStatus.COMPLETED, PlanStatus.ABANDONED):
                _print(
                    f"Plan `{plan_id}` is in {plan.status.value} status. "
                    "Only COMPLETED or ABANDONED plans can be reopened."
                )
                return ""

            if plan_manager.reopen_plan(plan_id):
                self.context.active_plan_id = plan_id
                _print(f"🔄 Plan `{plan_id}` ({plan.title}) reopened.")
                _print("Status changed to IN_PROGRESS.")

                # Show task summary
                plan = plan_manager.get_plan(plan_id)
                if plan and plan.tasks:
                    incomplete = len(plan.get_incomplete_tasks())
                    unverified = len(plan.get_unverified_tasks())
                    verified = len([t for t in plan.tasks if t.verified])
                    _print(
                        f"\n**Tasks:** {verified} verified, {unverified} unverified, "
                        f"{incomplete} incomplete"
                    )
                    _print("\nUse `/plan view` to see full plan details.")
            else:
                _print(f"Could not reopen plan `{plan_id}`.")
            return ""

        elif command == "move":
            # /plan move <id> [--local|--global]
            if len(args_list) < 2:
                _print("Usage: /plan move <id> [--local|--global]")
                return ""

            move_args = args_list[1].split()
            plan_id = move_args[0]
            target = LOCATION_LOCAL  # Default

            for arg in move_args[1:]:
                if arg == "--local":
                    target = LOCATION_LOCAL
                elif arg == "--global":
                    target = LOCATION_GLOBAL

            if target == LOCATION_LOCAL and not project_root:
                _print("Cannot move to local storage: not in a git repository.")
                return ""

            if plan_manager.move_plan(plan_id, target):
                emoji = _location_emoji(target)
                _print(f"{emoji} Plan `{plan_id}` moved to {target} storage.")
            else:
                _print(f"Could not move plan {plan_id}.")
            return ""

        elif command == "push":
            # /plan push [plan-id] [--workspace NAME] [--branch NAME] [--local PORT]
            # /plan push --all [--workspace-prefix PREFIX]
            import subprocess

            push_all = False
            plan_id = None
            workspace_name = None
            workspace_prefix = None
            branch_name = None
            local_port = None

            if len(args_list) >= 2:
                for arg in args_list[1].split():
                    if arg == "--all":
                        push_all = True
                    elif arg.startswith("--workspace="):
                        workspace_name = arg.split("=", 1)[1]
                    elif arg.startswith("--workspace-prefix="):
                        workspace_prefix = arg.split("=", 1)[1]
                    elif arg.startswith("--branch="):
                        branch_name = arg.split("=", 1)[1]
                    elif arg.startswith("--local="):
                        try:
                            local_port = int(arg.split("=", 1)[1])
                        except ValueError:
                            _print(f"Invalid port: {arg}")
                            return ""
                    elif arg == "--local":
                        local_port = 8000  # Default port
                    elif not plan_id and not arg.startswith("-"):
                        plan_id = arg

            def _validate_plan_in_vcs(plan):
                """Check if plan is in version control (not global or gitignored)."""
                if plan.storage_location == LOCATION_GLOBAL:
                    return False, "Plan is in global storage (not in repo)"
                return True, None

            def _get_repo_url():
                """Get the git remote URL for the current repo."""
                try:
                    result = subprocess.run(
                        ["git", "remote", "get-url", "origin"],
                        capture_output=True,
                        text=True,
                        cwd=root_dir,
                    )
                    if result.returncode == 0:
                        return result.stdout.strip()
                except Exception:
                    pass
                return None

            def _create_and_push_branch(branch: str):
                """Create branch, commit plan, and push."""
                try:
                    # Create and checkout new branch
                    subprocess.run(
                        ["git", "checkout", "-b", branch],
                        cwd=root_dir,
                        capture_output=True,
                        check=True,
                    )
                    # Add plan files
                    subprocess.run(
                        ["git", "add", ".agent/plans", ".silica/plans"],
                        cwd=root_dir,
                        capture_output=True,
                    )
                    # Commit if there are changes
                    subprocess.run(
                        ["git", "commit", "-m", "Add plan for remote execution"],
                        cwd=root_dir,
                        capture_output=True,
                    )
                    # Push branch
                    result = subprocess.run(
                        ["git", "push", "-u", "origin", branch],
                        cwd=root_dir,
                        capture_output=True,
                        text=True,
                    )
                    return result.returncode == 0, result.stderr
                except subprocess.CalledProcessError as e:
                    return False, str(e)

            def _push_single_plan(plan, ws_name=None, br_name=None, port=None):
                """Push a single plan to remote workspace."""
                valid, err = _validate_plan_in_vcs(plan)
                if not valid:
                    return False, f"Cannot push plan `{plan.id}`: {err}"

                # Generate names from slug
                slug = plan.get_slug()
                ws = ws_name or f"plan-{slug}"
                br = br_name or f"plan/{slug}"

                # Get repo URL
                repo_url = _get_repo_url()
                if not repo_url:
                    return False, "Could not determine repository URL"

                # Create and push the branch with plan files
                _print(f"Creating branch `{br}`...")
                success, err = _create_and_push_branch(br)
                if not success:
                    # Branch might already exist, try to checkout and push
                    subprocess.run(
                        ["git", "checkout", br], cwd=root_dir, capture_output=True
                    )
                    subprocess.run(
                        ["git", "push", "origin", br], cwd=root_dir, capture_output=True
                    )

                # Update plan with remote info
                plan.remote_workspace = ws
                plan.remote_branch = br
                plan.remote_started_at = datetime.now(timezone.utc)
                plan.shelved = False
                plan.add_progress(f"Pushed to remote workspace: {ws} (branch: {br})")
                plan_manager.update_plan(plan)

                # Create workspace and execute plan
                silica_dir = Path(root_dir) / ".silica"
                silica_dir.mkdir(exist_ok=True)

                try:
                    if port:
                        # Local workspace
                        from silica.remote.cli.commands.create import (
                            create_local_workspace,
                        )

                        _print(f"Creating local workspace `{ws}` on port {port}...")
                        create_local_workspace(ws, port, Path(root_dir), silica_dir, [])
                    else:
                        # Remote workspace
                        from silica.remote.cli.commands.create import (
                            create_remote_workspace,
                        )

                        _print(f"Creating remote workspace `{ws}`...")
                        create_remote_workspace(
                            ws, None, Path(root_dir), silica_dir, []
                        )

                    # Wait for workspace to be ready
                    import time

                    time.sleep(3)

                    # Execute plan via antennae
                    from silica.remote.utils.antennae_client import get_antennae_client

                    client = get_antennae_client(silica_dir, ws)

                    # Check if server supports execute-plan capability
                    supported, cap_error = client.supports_capability("execute-plan")
                    if not supported:
                        return False, cap_error

                    success, response = client.execute_plan(
                        repo_url=repo_url,
                        branch=br,
                        plan_id=plan.id,
                        plan_title=plan.title,
                        retries=5,
                    )

                    if success:
                        # Transition plan to IN_PROGRESS now that remote is executing
                        plan_manager.start_execution(plan.id)
                        return (
                            True,
                            f"📤 Plan `{plan.id}` ({plan.title})\n"
                            f"   Workspace: {ws}\n"
                            f"   Branch: {br}\n"
                            f"   Status: IN_PROGRESS (executing remotely)",
                        )
                    else:
                        return (
                            False,
                            f"Workspace created but plan execution failed: {response.get('error', 'Unknown error')}",
                        )

                except Exception as e:
                    return False, f"Failed to create workspace: {e}"

            if push_all:
                shelved = plan_manager.list_shelved_plans(root_dir=root_dir)
                if not shelved:
                    _print("No shelved plans to push.")
                    return ""

                # Validate all first
                errors = []
                for plan in shelved:
                    valid, err = _validate_plan_in_vcs(plan)
                    if not valid:
                        errors.append(f"  - `{plan.id}` ({plan.title}): {err}")

                if errors:
                    _print("❌ Cannot push all plans:\n" + "\n".join(errors))
                    return ""

                # Push each
                results = []
                prefix = workspace_prefix or "plan"
                base_port = local_port or 8000
                for i, plan in enumerate(shelved):
                    slug = plan.get_slug()
                    ws = f"{prefix}-{slug}"
                    br = f"plan/{slug}"
                    port = base_port + i if local_port else None
                    success, msg = _push_single_plan(plan, ws, br, port)
                    results.append(msg if success else f"❌ {msg}")

                _print("## Pushed Plans\n\n" + "\n\n".join(results))
                return ""

            else:
                # Push single plan
                if not plan_id:
                    if self.context.active_plan_id:
                        plan_id = self.context.active_plan_id
                    else:
                        shelved = plan_manager.list_shelved_plans(root_dir=root_dir)
                        if shelved:
                            plan_id = shelved[0].id
                        else:
                            _print("No plan specified and no shelved plans found.")
                            _print(
                                "Usage: /plan push <plan-id> [--workspace=NAME] [--branch=NAME] [--local=PORT]"
                            )
                            return ""

                plan = plan_manager.get_plan(plan_id)
                if not plan:
                    _print(f"Plan `{plan_id}` not found.")
                    return ""

                success, msg = _push_single_plan(
                    plan, workspace_name, branch_name, local_port
                )
                if success:
                    _print(msg)
                else:
                    _print(f"❌ {msg}")
                return ""

        elif command == "status":
            # /plan status [id] [--remote]
            # If id provided, show detailed status for that plan
            # If --remote flag, only show plans with remote workspaces
            plan_id = None
            show_remote_only = False

            if len(args_list) >= 2:
                for arg in args_list[1].split():
                    if arg == "--remote":
                        show_remote_only = True
                    elif not arg.startswith("-") and not plan_id:
                        plan_id = arg

            # If specific plan ID requested, show detailed status
            if plan_id:
                plan = plan_manager.get_plan(plan_id)
                if not plan:
                    _print(f"Plan `{plan_id}` not found.")
                    return ""

                loc = _location_emoji(plan.storage_location)
                output = f"## {loc} Plan: {plan.title}\n\n"
                output += f"**ID:** {plan.id}\n"
                output += f"**Status:** {plan.status.value}"
                if plan.shelved:
                    output += " (shelved)"
                output += "\n"

                # Task progress (local)
                if plan.tasks:
                    done = sum(1 for t in plan.tasks if t.completed)
                    verified = sum(1 for t in plan.tasks if t.verified)
                    total = len(plan.tasks)
                    output += (
                        f"**Tasks:** {done}/{total} done, {verified}/{total} verified\n"
                    )

                # Remote info and status
                if plan.remote_workspace:
                    output += "\n### Remote Execution\n"
                    output += f"**Workspace:** {plan.remote_workspace}\n"
                    if plan.remote_branch:
                        output += f"**Branch:** {plan.remote_branch}\n"
                    if plan.remote_started_at:
                        from silica.developer.utils import format_elapsed_time

                        elapsed = (
                            datetime.now(timezone.utc) - plan.remote_started_at
                        ).total_seconds()
                        output += f"**Elapsed:** {format_elapsed_time(elapsed)}\n"

                    # Fetch remote status
                    output += "\n**Fetching remote status...**\n"
                    _print(output)

                    try:
                        from silica.remote.utils.antennae_client import (
                            get_antennae_client,
                        )

                        silica_dir = Path(root_dir) / ".silica"
                        client = get_antennae_client(silica_dir, plan.remote_workspace)

                        # Check if server supports plan-status
                        supported, _ = client.supports_capability("plan-status")
                        if not supported:
                            _print(
                                "Remote server does not support plan-status. Upgrade antennae."
                            )
                            return ""

                        success, remote_status = client.get_plan_status(plan.id)
                        if success:
                            remote_output = "**Remote Status:**\n"
                            remote_output += (
                                f"  Status: {remote_status.get('status', 'unknown')}\n"
                            )
                            remote_output += f"  Agent: {remote_status.get('agent_status', 'unknown')}\n"

                            tasks_done = remote_status.get("tasks_completed", 0)
                            tasks_verified = remote_status.get("tasks_verified", 0)
                            tasks_total = remote_status.get("tasks_total", 0)
                            if tasks_total > 0:
                                remote_output += f"  Tasks: {tasks_done}/{tasks_total} done, {tasks_verified}/{tasks_total} verified\n"

                            current_task = remote_status.get("current_task")
                            if current_task:
                                remote_output += f"  Current: {current_task}\n"

                            _print(remote_output)
                        else:
                            _print(
                                f"Failed to fetch remote status: {remote_status.get('error', 'Unknown error')}"
                            )
                    except Exception as e:
                        _print(f"Could not connect to remote: {e}")

                    return ""

                if plan.pull_request:
                    output += f"**PR:** {plan.pull_request}\n"

                _print(output)
                return ""

            # List all active plans
            plans = plan_manager.list_active_plans(root_dir=root_dir)
            if show_remote_only:
                plans = [p for p in plans if p.remote_workspace]

            if not plans:
                if show_remote_only:
                    _print("No plans executing remotely.")
                else:
                    _print("No active plans.")
                return ""

            output = "## Plan Status\n\n"
            for plan in plans:
                loc = _location_emoji(plan.storage_location)
                status_str = plan.status.value
                if plan.shelved:
                    status_str += " (shelved)"

                output += f"{loc} **{plan.id}** - {plan.title}\n"
                output += f"   Status: {status_str}\n"

                if plan.remote_workspace:
                    output += f"   Remote: {plan.remote_workspace}\n"
                    if plan.remote_started_at:
                        from silica.developer.utils import format_elapsed_time

                        elapsed = (
                            datetime.now(timezone.utc) - plan.remote_started_at
                        ).total_seconds()
                        output += f"   Elapsed: {format_elapsed_time(elapsed)}\n"
                if plan.remote_branch:
                    output += f"   Branch: {plan.remote_branch}\n"
                if plan.pull_request:
                    output += f"   PR: {plan.pull_request}\n"

                # Task progress
                if plan.tasks:
                    done = sum(1 for t in plan.tasks if t.completed)
                    verified = sum(1 for t in plan.tasks if t.verified)
                    total = len(plan.tasks)
                    output += (
                        f"   Tasks: {done}/{total} done, {verified}/{total} verified\n"
                    )

                output += "\n"

            _print(output)
            return ""

        elif command == "new" or command not in subcommands:
            # /plan new or /plan <topic> - create a new plan with agent

            # Parse --local/--global flags
            force_location = None
            remaining_args = []

            if command == "new" and len(args_list) > 1:
                for arg in args_list[1].split():
                    if arg == "--local":
                        force_location = LOCATION_LOCAL
                    elif arg == "--global":
                        force_location = LOCATION_GLOBAL
                    else:
                        remaining_args.append(arg)

            # Get topic (either from args or prompt user)
            if command == "new":
                # /plan new or /plan new <topic>
                if remaining_args:
                    topic = " ".join(remaining_args)
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

            # Determine storage location for display
            if force_location:
                loc_display = f" ({_location_emoji(force_location)} {force_location})"
            elif project_root:
                loc_display = f" ({_location_emoji(LOCATION_LOCAL)} local)"
            else:
                loc_display = f" ({_location_emoji(LOCATION_GLOBAL)} global)"

            _print(
                f"📋 **Entering Plan Mode**{loc_display}\n\nTopic: {topic}\n\nThe agent will now help you create a structured plan..."
            )

            # Build location hint for agent
            location_hint = ""
            if force_location:
                location_hint = f', location="{force_location}"'

            # Create the planning prompt to send to agent
            planning_prompt = f"""I'd like to enter plan mode to work on: {topic}

Please use the `enter_plan_mode` tool to start planning this{location_hint}. Then:
1. Analyze what's needed for this task
2. Ask me clarifying questions using `ask_clarifications` if anything is unclear
3. Document the implementation approach using `update_plan`
4. Break down the work into tasks using `add_plan_tasks`

Let's collaborate on creating a solid plan before implementation."""

            # Return (content, auto_add=True) to automatically add to conversation
            # and trigger agent response
            return (planning_prompt, True)

    async def _island(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Manage Agent Island connection.

        Usage:
            /island                   - Show Island connection status
            /island status            - Same as /island
            /island reconnect         - Force reconnect to Island
            /island disconnect        - Disconnect from Island

        Examples:
            /island                   - Check if Island is connected
            /island reconnect         - Reconnect after Island restart
        """

        def _print(msg, markdown=True):
            """Print directly to user without adding to conversation."""
            user_interface.handle_system_message(msg, markdown=markdown)

        # Check if we have a hybrid interface
        if not hasattr(user_interface, "_island"):
            _print(
                "[yellow]Island integration not available in this interface.[/yellow]"
            )
            return ("", False)

        args_list = user_input.strip().split() if user_input.strip() else []
        command = args_list[0].lower() if args_list else "status"

        if command == "status" or not args_list:
            return self._island_status(_print, user_interface)

        elif command == "reconnect":
            return await self._island_reconnect(_print, user_interface)

        elif command == "disconnect":
            return await self._island_disconnect(_print, user_interface)

        else:
            _print(
                f"[red]Unknown island command: {command}[/red]\n"
                "Use /help island for usage information."
            )
            return ("", False)

    def _island_status(self, _print, user_interface):
        """Show Island connection status."""
        island = getattr(user_interface, "_island", None)
        lines = ["[bold]Agent Island Status:[/bold]", ""]

        # Check socket path
        socket_path = getattr(user_interface, "socket_path", None)
        if socket_path:
            lines.append(f"**Socket Path:** `{socket_path}`")
            if socket_path.exists():
                lines.append("**Socket Exists:** ✓ Yes")
            else:
                lines.append("**Socket Exists:** ✗ No")
        else:
            lines.append("**Socket Path:** Not configured")

        # Check connection status
        if island is None:
            lines.append("**Connection:** ✗ Not initialized")
            lines.append("")
            lines.append("[dim]Island client has not been created yet.[/dim]")
        elif island.connected:
            lines.append("**Connection:** ✓ Connected")

            # Show version if available
            version = island.island_version
            if version:
                lines.append(f"**Island Version:** {version}")

            # Show reconnecting status
            if island.reconnecting:
                lines.append("**Status:** 🔄 Reconnecting...")
            else:
                lines.append("**Status:** Ready")
        else:
            lines.append("**Connection:** ✗ Disconnected")
            if island.reconnecting:
                lines.append("**Status:** 🔄 Attempting to reconnect...")
            else:
                lines.append("**Status:** Idle")

        _print("\n".join(lines))
        return ("", False)

    async def _island_reconnect(self, _print, user_interface):
        """Force reconnect to Island."""
        island = getattr(user_interface, "_island", None)
        lines = []

        if island is None:
            # Try to create a new connection
            lines.append("Attempting to connect to Island...")
            if hasattr(user_interface, "connect_to_island"):
                connected = await user_interface.connect_to_island()
                if connected:
                    lines.append("[green]✓ Connected to Island[/green]")
                else:
                    lines.append("[red]✗ Failed to connect to Island[/red]")
                    lines.append("[dim]Make sure Agent Island is running.[/dim]")
            else:
                lines.append("[red]✗ Island connection not supported[/red]")
            _print("\n".join(lines))
            return ("", False)

        # Disconnect first if connected
        if island.connected:
            lines.append("Disconnecting from Island...")
            await island.disconnect()

        # Reconnect
        lines.append("Reconnecting to Island...")
        try:
            connected = await island.connect()
            if connected:
                lines.append("[green]✓ Reconnected to Island[/green]")

                # Re-register session if we have context
                if self.context and self.context.session_id:
                    try:
                        await island.register_session(
                            session_id=self.context.session_id,
                            name="Silica Session",
                        )
                        lines.append("[dim]Session re-registered[/dim]")
                    except Exception as e:
                        lines.append(
                            f"[yellow]Warning: Could not re-register session: {e}[/yellow]"
                        )
            else:
                lines.append("[red]✗ Failed to reconnect[/red]")
                lines.append("[dim]Make sure Agent Island is running.[/dim]")
        except Exception as e:
            lines.append(f"[red]✗ Reconnection failed: {e}[/red]")

        _print("\n".join(lines))
        return ("", False)

    async def _island_disconnect(self, _print, user_interface):
        """Disconnect from Island."""
        island = getattr(user_interface, "_island", None)

        if island is None:
            _print("[yellow]Not connected to Island[/yellow]")
            return ("", False)

        if not island.connected:
            _print("[yellow]Already disconnected from Island[/yellow]")
            return ("", False)

        lines = ["Disconnecting from Island..."]
        try:
            await island.disconnect()
            lines.append("[green]✓ Disconnected from Island[/green]")
        except Exception as e:
            lines.append(f"[red]✗ Disconnect failed: {e}[/red]")

        _print("\n".join(lines))
        return ("", False)

    async def _mcp(self, user_interface, sandbox, user_input, *args, **kwargs):
        """Manage MCP server connections and tools.

        Usage:
            /mcp                      - Show MCP server status
            /mcp status               - Same as /mcp
            /mcp connect [server]     - Connect to server(s)
            /mcp disconnect [server]  - Disconnect from server(s)
            /mcp reconnect [server]   - Reconnect to server(s)
            /mcp refresh [server]     - Force refresh tool schemas
            /mcp cache <server> <on|off>  - Toggle caching for a server
            /mcp enable <server>      - Enable server for auto-connect at startup
            /mcp disable <server>     - Disable server from auto-connecting
            /mcp tools [server]       - List tools from server(s)
            /mcp setup <server>       - Run server's setup/auth flow
            /mcp add <name> <cmd> [args]  - Add a server to config
            /mcp remove <name>        - Remove a server from config

        Examples:
            /mcp                      - Show all servers with status
            /mcp connect sqlite       - Connect to sqlite server
            /mcp tools                - List all MCP tools
            /mcp cache myserver off   - Disable caching for development
            /mcp disable sqlite       - Stop sqlite from auto-connecting
            /mcp setup gdrive         - Run gdrive server's auth setup
            /mcp add github npx -y @modelcontextprotocol/server-github
            /mcp remove github        - Remove github server
        """

        def _print(msg, markdown=True):
            """Print directly to user without adding to conversation."""
            user_interface.handle_system_message(msg, markdown=markdown)

        # Check if MCP is available
        if self.mcp_manager is None:
            _print("[yellow]MCP is not configured. No MCP servers found in:[/yellow]")
            _print("  - ~/.silica/mcp_servers.json (global)")
            _print("  - ~/.silica/personas/<persona>/mcp_servers.json (per-persona)")
            _print("  - .silica/mcp_servers.json (per-project)")
            return ("", False)

        args_list = user_input.strip().split() if user_input.strip() else []
        command = args_list[0].lower() if args_list else "status"

        if command == "status" or not args_list:
            # Show status of all servers
            return self._mcp_status(_print)

        elif command == "connect":
            server_name = args_list[1] if len(args_list) > 1 else None
            return await self._mcp_connect(_print, server_name)

        elif command == "disconnect":
            server_name = args_list[1] if len(args_list) > 1 else None
            return await self._mcp_disconnect(_print, server_name)

        elif command == "reconnect":
            server_name = args_list[1] if len(args_list) > 1 else None
            return await self._mcp_reconnect(_print, server_name)

        elif command == "refresh":
            server_name = args_list[1] if len(args_list) > 1 else None
            return await self._mcp_refresh(_print, server_name)

        elif command == "cache":
            if len(args_list) < 3:
                _print("[red]Usage: /mcp cache <server> <on|off>[/red]")
                return ("", False)
            server_name = args_list[1]
            enabled = args_list[2].lower() in ("on", "true", "1", "yes")
            return self._mcp_set_cache(_print, server_name, enabled)

        elif command == "enable":
            if len(args_list) < 2:
                _print("[red]Usage: /mcp enable <server>[/red]")
                return ("", False)
            return self._mcp_set_enabled(_print, args_list[1], True)

        elif command == "disable":
            if len(args_list) < 2:
                _print("[red]Usage: /mcp disable <server>[/red]")
                return ("", False)
            return self._mcp_set_enabled(_print, args_list[1], False)

        elif command == "tools":
            server_name = args_list[1] if len(args_list) > 1 else None
            return self._mcp_tools(_print, server_name)

        elif command == "setup":
            # /mcp setup <server> - run server's setup/auth flow
            if len(args_list) < 2:
                _print("[red]Usage: /mcp setup <server>[/red]")
                return ("", False)
            return await self._mcp_setup(_print, args_list[1])

        elif command == "add":
            # /mcp add <name> <command> [args...]
            if len(args_list) < 3:
                _print("[red]Usage: /mcp add <name> <command> [args...][/red]")
                _print(
                    "Example: /mcp add sqlite uvx mcp-server-sqlite --db-path /tmp/test.db"
                )
                return ("", False)
            return self._mcp_add(_print, args_list[1], args_list[2], args_list[3:])

        elif command == "remove":
            # /mcp remove <name>
            if len(args_list) < 2:
                _print("[red]Usage: /mcp remove <name>[/red]")
                return ("", False)
            return self._mcp_remove(_print, args_list[1])

        else:
            _print(f"[red]Unknown MCP command: {command}[/red]")
            _print("Use /help mcp for usage information.")
            return ("", False)

    def _mcp_status(self, _print):
        """Show status of all MCP servers."""
        statuses = self.mcp_manager.get_server_status()

        if not statuses:
            _print("[yellow]No MCP servers configured.[/yellow]")
            return ("", False)

        lines = ["[bold]MCP Servers:[/bold]"]
        for status in statuses:
            # Build status line
            conn_icon = "✓" if status.connected else "✗"
            conn_color = "green" if status.connected else "red"
            conn_text = "connected" if status.connected else "disconnected"

            tool_text = f"{status.tool_count:2d} tools" if status.connected else ""
            cache_text = f"cache: {'on' if status.cache_enabled else 'off'}"

            # Extra status indicators
            extra = []
            if status.needs_setup:
                extra.append("[yellow]⚠ needs setup[/yellow]")
            if not status.enabled:
                extra.append("[dim]disabled[/dim]")
            extra_text = "  " + " ".join(extra) if extra else ""

            lines.append(
                f"  {status.name:16} [{conn_color}]{conn_icon} {conn_text:12}[/{conn_color}]"
                f"  {tool_text:10}  {cache_text}{extra_text}"
            )

        _print("\n".join(lines))
        return ("", False)

    async def _mcp_connect(self, _print, server_name):
        """Connect to MCP server(s)."""
        if server_name:
            try:
                await self.mcp_manager.connect_server(server_name)
                client = self.mcp_manager._clients.get(server_name)
                tool_count = len(client.tools) if client else 0
                _print(
                    f"[green]Connected to '{server_name}' with {tool_count} tools[/green]"
                )
            except ValueError as e:
                _print(f"[red]{e}[/red]")
            except Exception as e:
                _print(f"[red]Failed to connect to '{server_name}': {e}[/red]")
        else:
            # Connect all enabled servers
            if not self.mcp_manager._config:
                _print("[red]No MCP configuration loaded[/red]")
                return ("", False)

            results = await self.mcp_manager.connect_servers(self.mcp_manager._config)
            connected = [n for n, e in results.items() if e is None]
            failed = [(n, e) for n, e in results.items() if e is not None]

            if connected:
                _print(f"[green]Connected to {len(connected)} server(s)[/green]")
            for name, err in failed:
                _print(f"[red]Failed to connect to '{name}': {err}[/red]")

        return ("", False)

    async def _mcp_disconnect(self, _print, server_name):
        """Disconnect from MCP server(s)."""
        if server_name:
            await self.mcp_manager.disconnect_server(server_name)
            _print(f"[yellow]Disconnected from '{server_name}'[/yellow]")
        else:
            # Disconnect all
            server_names = list(self.mcp_manager._clients.keys())
            await self.mcp_manager.disconnect_all()
            _print(f"[yellow]Disconnected from {len(server_names)} server(s)[/yellow]")

        return ("", False)

    async def _mcp_reconnect(self, _print, server_name):
        """Reconnect to MCP server(s)."""
        if server_name:
            await self.mcp_manager.disconnect_server(server_name)
            await self._mcp_connect(_print, server_name)
        else:
            # Reconnect all
            server_names = list(self.mcp_manager._clients.keys())
            await self.mcp_manager.disconnect_all()
            if self.mcp_manager._config:
                await self.mcp_manager.connect_servers(self.mcp_manager._config)
            _print(f"[green]Reconnected to {len(server_names)} server(s)[/green]")

        return ("", False)

    async def _mcp_refresh(self, _print, server_name):
        """Force refresh tool schemas."""
        try:
            await self.mcp_manager.refresh_schemas(server_name)
            if server_name:
                _print(f"[green]Refreshed schemas from '{server_name}'[/green]")
            else:
                _print("[green]Refreshed schemas from all servers[/green]")
        except Exception as e:
            _print(f"[red]Failed to refresh schemas: {e}[/red]")

        return ("", False)

    def _mcp_set_cache(self, _print, server_name, enabled):
        """Toggle caching for an MCP server."""
        try:
            self.mcp_manager.set_cache_enabled(server_name, enabled)
            status = "on" if enabled else "off"
            _print(f"[green]Set cache={status} for '{server_name}'[/green]")
        except ValueError as e:
            _print(f"[red]{e}[/red]")

        return ("", False)

    def _mcp_set_enabled(self, _print, server_name, enabled):
        """Enable or disable an MCP server for auto-connect at startup."""
        import json
        from pathlib import Path

        from silica.developer.mcp.config import MCPConfig, save_mcp_config

        # Try each config location in order: project, persona, global
        silica_dir = Path.home() / ".silica"
        locations_to_try = []

        # Project config
        project_path = Path.cwd() / ".silica" / "mcp_servers.json"
        if project_path.exists():
            locations_to_try.append(("project", project_path, Path.cwd(), None))

        # Persona config (if we can determine it)
        if self.context and self.context.history_base_dir:
            history_path = Path(self.context.history_base_dir)
            if history_path.parent.name == "personas":
                persona = history_path.name
                persona_path = silica_dir / "personas" / persona / "mcp_servers.json"
                if persona_path.exists():
                    locations_to_try.append(("persona", persona_path, None, persona))

        # Global config
        global_path = silica_dir / "mcp_servers.json"
        if global_path.exists():
            locations_to_try.append(("global", global_path, None, None))

        # Find which config contains this server
        for location, path, project_root, persona in locations_to_try:
            try:
                config = MCPConfig.from_file(path)
                if server_name in config.servers:
                    # Found it - update and save
                    config.servers[server_name].enabled = enabled
                    save_mcp_config(
                        config,
                        location=location,
                        project_root=project_root,
                        persona=persona,
                    )
                    status = "enabled" if enabled else "disabled"
                    note = (
                        " (will auto-connect on startup)"
                        if enabled
                        else " (won't auto-connect)"
                    )
                    _print(f"[green]Server '{server_name}' {status}{note}[/green]")
                    return ("", False)
            except (json.JSONDecodeError, KeyError):
                continue

        _print(f"[red]Server '{server_name}' not found in any config[/red]")
        return ("", False)

    def _mcp_tools(self, _print, server_name):
        """List tools from MCP server(s)."""
        tools = self.mcp_manager.get_all_tools()

        if server_name:
            tools = [t for t in tools if t.server_name == server_name]

        if not tools:
            if server_name:
                _print(f"[yellow]No tools from server '{server_name}'[/yellow]")
            else:
                _print("[yellow]No MCP tools available[/yellow]")
            return ("", False)

        # Group tools by server
        by_server: dict[str, list] = {}
        for tool in tools:
            by_server.setdefault(tool.server_name, []).append(tool)

        for srv_name, srv_tools in sorted(by_server.items()):
            _print(f"\n[bold]{srv_name}[/bold] ({len(srv_tools)} tools)")
            for tool in sorted(srv_tools, key=lambda t: t.name):
                desc = (
                    tool.description[:60] + "..."
                    if len(tool.description) > 60
                    else tool.description
                )
                _print(f"  {tool.name}: {desc}")

        return ("", False)

    async def _mcp_setup(self, _print, server_name):
        """Run setup/auth flow for an MCP server.

        This runs the server's configured setup_command, which typically
        triggers the server's own authentication flow (e.g., OAuth browser flow).
        """
        import subprocess

        if not self.mcp_manager._config:
            _print("[red]No MCP configuration loaded[/red]")
            return ("", False)

        server_config = self.mcp_manager._config.servers.get(server_name)
        if not server_config:
            _print(f"[red]Server '{server_name}' not found[/red]")
            return ("", False)

        if not server_config.has_setup_command():
            # No setup command configured - try running the server directly
            # Many MCP servers trigger auth on first run
            _print(
                f"[yellow]Server '{server_name}' has no setup_command configured.[/yellow]"
            )
            _print("Attempting to run the server directly (this may trigger auth)...")
            _print("")

            # Build command from server config
            cmd = [server_config.command] + server_config.args
            setup_command = server_config.command
            setup_args = server_config.args
        else:
            setup_command = server_config.setup_command
            setup_args = server_config.setup_args
            cmd = [setup_command] + setup_args

        _print(f"Running: {' '.join(cmd)}")
        _print("")

        try:
            # Run interactively so user can complete auth flow
            result = subprocess.run(
                cmd,
                env={**dict(__import__("os").environ), **server_config.env},
                timeout=300,  # 5 minute timeout for interactive auth
            )

            if result.returncode == 0:
                _print("")
                _print(f"[green]✓ Setup completed for '{server_name}'[/green]")

                # Check if setup created credentials
                if server_config.credentials_path:
                    from pathlib import Path
                    from silica.developer.mcp.config import expand_env_vars

                    creds_path = Path(expand_env_vars(server_config.credentials_path))
                    if creds_path.exists():
                        _print(f"[green]✓ Credentials found at {creds_path}[/green]")
                    else:
                        _print(
                            f"[yellow]⚠ Credentials not found at {creds_path}[/yellow]"
                        )

                # Try to connect the server
                _print("Attempting to connect...")
                try:
                    await self.mcp_manager.connect_server(server_name)
                    client = self.mcp_manager._clients.get(server_name)
                    tool_count = len(client.tools) if client else 0
                    _print(
                        f"[green]✓ Connected to '{server_name}' with {tool_count} tools[/green]"
                    )
                except Exception as e:
                    _print(f"[yellow]Could not connect: {e}[/yellow]")
                    _print(
                        "You may need to run setup again or check the configuration."
                    )

            else:
                _print("")
                _print(f"[red]✗ Setup failed with exit code {result.returncode}[/red]")

            return ("", False)

        except subprocess.TimeoutExpired:
            _print("[red]✗ Setup timed out after 5 minutes[/red]")
            return ("", False)
        except FileNotFoundError:
            _print(f"[red]✗ Command not found: {setup_command}[/red]")
            _print("Make sure the server package is installed.")
            return ("", False)
        except Exception as e:
            _print(f"[red]✗ Setup failed: {e}[/red]")
            return ("", False)

    def _mcp_add(self, _print, name, command, args):
        """Add an MCP server to the global config."""
        from silica.developer.mcp.config import add_mcp_server

        try:
            path = add_mcp_server(
                name=name,
                command=command,
                args=args,
            )
            _print(f"[green]✓ Added server '{name}' to {path}[/green]")
            _print(f"  command: {command}")
            if args:
                _print(f"  args: {' '.join(args)}")
            _print("")
            _print(f"Use [bold]/mcp connect {name}[/bold] to connect now")
            _print("Or restart the session to auto-connect")
            return ("", False)
        except Exception as e:
            _print(f"[red]Error adding server: {e}[/red]")
            return ("", False)

    def _mcp_remove(self, _print, name):
        """Remove an MCP server from the global config."""
        from silica.developer.mcp.config import remove_mcp_server

        try:
            removed = remove_mcp_server(name=name)
            if removed:
                _print(f"[green]✓ Removed server '{name}' from config[/green]")

                # Disconnect if currently connected
                if self.mcp_manager and name in self.mcp_manager._clients:
                    import asyncio

                    asyncio.create_task(self.mcp_manager.disconnect_server(name))
                    _print(f"[dim]Disconnected from '{name}'[/dim]")
            else:
                _print(f"[yellow]Server '{name}' not found in global config[/yellow]")
            return ("", False)
        except Exception as e:
            _print(f"[red]Error removing server: {e}[/red]")
            return ("", False)

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

        User tools with invalid schemas are silently skipped to prevent API failures
        that would affect all agent instances due to hot reloading.
        """
        schemas = []

        # Collect valid user tool names first (they take precedence)
        # Only include tools with valid schemas to prevent API failures
        valid_user_tool_names = set()
        for name, tool in self.user_tools.items():
            if tool.spec and tool.schema_valid:
                valid_user_tool_names.add(name)

        # Built-in tools (skip if valid user tool with same name exists)
        for tool in self.agent_tools:
            if hasattr(tool, "schema"):
                schema = tool.schema()
                tool_name = schema.get("name", tool.__name__)
                # Skip built-in tools that have user tool replacements
                if tool_name not in valid_user_tool_names:
                    schemas.append(schema)

        # User-created tools (only include those with valid schemas)
        for name, tool in self.user_tools.items():
            if tool.spec and tool.schema_valid:
                schemas.append(tool.spec)
            # Silently skip invalid tools - they will be shown in /tools with errors

        # MCP server tools (if manager is configured)
        if self.mcp_manager:
            try:
                # Get MCP tool schemas synchronously from cache
                # Note: For servers with cache=False, this will use cached tools
                # The actual refresh happens at connection time or via refresh_mcp_tools()
                mcp_tools = self.mcp_manager.get_all_tools()
                for tool in mcp_tools:
                    schemas.append(tool.to_anthropic_schema())
            except Exception as e:
                # Log but don't fail if MCP tools unavailable
                import logging

                logging.getLogger(__name__).warning(
                    f"Failed to get MCP tool schemas: {e}"
                )

        if schemas and enable_caching:
            schemas[-1]["cache_control"] = {"type": "ephemeral"}
        return schemas
