import copy
import os
import time
import random
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import anthropic
import httpx
from anthropic.types import TextBlock, MessageParam
from dotenv import load_dotenv

from silica.developer.context import AgentContext
from silica.developer.loop_detection import LoopDetector
from silica.developer.models import ModelSpec
from silica.developer.prompt import create_system_message
from silica.developer.rate_limiter import RateLimiter
from silica.developer.toolbox import Toolbox
from silica.developer.sandbox import DoSomethingElseError

# MCP imports - optional, only used if MCP servers are configured
try:
    from silica.developer.mcp import MCPToolManager, load_mcp_config

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


def get_thinking_config(thinking_mode: str, model_spec: ModelSpec) -> dict | None:
    """Get the thinking configuration for the API call based on the current mode.

    Args:
        thinking_mode: One of "off", "normal", or "ultra"
        model_spec: The model specification dict

    Returns:
        Thinking config dict for API call, or None if thinking is off or unsupported
    """
    # Check if model supports thinking
    if not model_spec.get("thinking_support", False):
        return {"type": "disabled"}

    if thinking_mode == "off":
        return None
    elif thinking_mode == "normal":
        return {"type": "enabled", "budget_tokens": 8000}
    elif thinking_mode == "ultra":
        return {"type": "enabled", "budget_tokens": 20000}
    else:
        return {"type": "disabled"}


def retry_with_exponential_backoff(func, max_retries=5, base_delay=1, max_delay=60):
    def wrapper(*args, **kwargs):
        retries = 0
        rate_limiter = RateLimiter()

        while retries < max_retries:
            try:
                return func(*args, **kwargs)
            except anthropic.RateLimitError as e:
                # Special handling for rate limit errors to respect Anthropic's tokens reset time
                retries += 1
                if retries == max_retries:
                    raise

                # Extract information from the rate limit error
                backoff_time = rate_limiter.handle_rate_limit_error(e)

                print(
                    f"Rate limit error encountered. Retrying in {backoff_time:.2f} seconds... (Attempt {retries}/{max_retries})"
                )
                # Wait time is already handled in handle_rate_limit_error

            except (anthropic.APIError, anthropic.APIStatusError) as e:
                if isinstance(e, anthropic.APIError) and e.status_code not in [
                    429,
                    500,
                    503,
                    529,
                ]:
                    raise

                retries += 1
                if retries == max_retries:
                    raise

                delay = min(base_delay * (2**retries) + random.uniform(0, 1), max_delay)
                print(
                    f"Server error or overload encountered. Retrying in {delay:.2f} seconds... (Attempt {retries}/{max_retries})"
                )
                time.sleep(delay)

        return func(*args, **kwargs)

    return wrapper


def _extract_file_mentions(message: MessageParam) -> list[Path]:
    """Extract file mentions from a message that start with @ and resolve to actual files.

    File mentions are substrings that:
    - Start with @
    - Contain no breaks or backslash escapes
    - Resolve to an actual file on the filesystem (not directories)
    - Have trailing punctuation removed (period, comma, semicolon, etc.)
    - Are converted to relative paths when possible

    Note: This function only extracts the file mentions but does not read the files.
    Access to file contents is controlled by the sandbox when this is used in
    combination with other functions.

    Args:
        message: The message to extract file mentions from

    Returns:
        List of Path objects for files that were mentioned and exist
    """
    if isinstance(message["content"], str):
        content = message["content"]
    elif isinstance(message["content"], list):
        # For messages with multiple content blocks, concatenate text blocks
        content = " ".join(
            block["text"]
            for block in message["content"]
            if isinstance(block, dict) and "text" in block
        )
    else:
        return []

    # Split on whitespace and get tokens starting with @
    words = content.split()
    # Get words starting with @ and strip trailing punctuation
    file_mentions = []
    for word in words:
        if word.startswith("@"):
            # Remove @ prefix and strip common punctuation from the end
            mention = word[1:].rstrip(".,;:!?")
            if mention:  # Only add if there's content after @ and punctuation removal
                file_mentions.append(mention)

    # Convert to paths, filter to existing files, and ensure they are files (not directories)
    paths = []
    for mention in file_mentions:
        path = Path(mention)
        if path.exists() and path.is_file():
            # Convert to relative path if possible
            try:
                relative_path = path.relative_to(Path.cwd())
                paths.append(relative_path)
            except ValueError:
                # If we can't make it relative, use the original path
                paths.append(path)

    return paths


def _should_inject_plan_reminder(
    agent_context: "AgentContext",
) -> tuple[bool, str | None]:
    """Determine if a plan state reminder should be injected.

    Plan reminders should only be injected when:
    - There's an active plan in "executing" state
    - The plan has incomplete tasks
    - This is not a subagent (subagents have their own focused task)

    This is called when the assistant responds WITHOUT tool_use blocks,
    meaning it's about to return control to the user. The reminder nudges
    the agent to continue working on the plan instead of stopping.

    Args:
        agent_context: The agent context to check

    Returns:
        Tuple of (should_inject: bool, plan_state: str | None)
    """
    # Don't inject for subagents - they have their own focused task
    if agent_context.parent_session_id is not None:
        return False, None

    try:
        from silica.developer.tools.planning import (
            get_active_plan_status,
            get_ephemeral_plan_state,
        )

        plan_status = get_active_plan_status(agent_context)
        if not plan_status:
            return False, None

        # Only inject if plan is in executing state with incomplete tasks
        if plan_status.get("status") != "executing":
            return False, None

        incomplete_tasks = plan_status.get("incomplete_tasks", 0)
        if incomplete_tasks == 0:
            return False, None

        # Get the ephemeral plan state message
        plan_state = get_ephemeral_plan_state(agent_context)
        if not plan_state:
            return False, None

        return True, plan_state

    except Exception:
        # Don't fail if planning module has issues
        return False, None


def _process_file_mentions(
    chat_history: list[MessageParam],
    agent_context: "AgentContext",
) -> list[MessageParam]:
    """Process file mentions in chat history and inline their contents into the messages.

    This function operates outside the sandbox system, treating @ mentions as explicit
    permission to read the referenced files. This is in contrast to other file operations
    that require sandbox permission checks.

    Security Note: This direct file access could potentially be exploited if code is
    copy/pasted into the system or if a sub-agent tool is used where the user message
    originates from a higher-level agent. Care should be taken when processing file
    mentions from untrusted sources.

    Args:
        chat_history: List of message parameters from the conversation history
        agent_context: Agent context (used for future extensions)

    Returns:
        Modified chat history with file contents inlined into the messages
    """
    file_mention_map: dict[Path, list[int]] = defaultdict(list)
    # Make a deep copy of the chat history to ensure we don't modify the original
    results: list[MessageParam] = []

    # First, make a direct deep copy of each message
    for idx, message in enumerate(chat_history):
        message_copy = copy.deepcopy(message)
        results.append(message_copy)

        if message["role"] == "user":
            file_mentions = _extract_file_mentions(message)
            for file_mention in file_mentions:
                file_mention_map[file_mention].append(idx)

    # Now update the messages with file contents
    for mentioned_file, message_indexes in file_mention_map.items():
        last_index = message_indexes[-1]
        message_to_update = results[last_index]

        # Read the file content
        try:
            with open(mentioned_file, "r") as f:
                file_content = f.read()
        except Exception as e:
            print(f"Warning: Could not read file {mentioned_file}: {e}")
            continue

        # Format the file content block
        relative_path = mentioned_file.as_posix()
        file_block = (
            f"<mentioned_file path={relative_path}>\n{file_content}\n</mentioned_file>"
        )

        # Convert message content to list format if it's a string
        if isinstance(message_to_update["content"], str):
            message_to_update["content"] = [
                {"type": "text", "text": message_to_update["content"]}
            ]

        # Add the file content as a new text block
        message_to_update["content"].append({"type": "text", "text": file_block})

    # Handle cache_control: API allows max 4 blocks with cache_control.
    # We need to:
    # 1. Strip old cache_control from all messages except the last few
    # 2. Add cache_control to the last user message

    # First, strip all existing cache_control from messages
    for msg in results:
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and "cache_control" in block:
                    del block["cache_control"]

    # Now add cache_control to the last user message only
    if results and results[-1]["role"] == "user":
        last_message = results[-1]
        # Ensure content is in the proper list format
        if isinstance(last_message["content"], str):
            last_message["content"] = [
                {"type": "text", "text": last_message["content"]}
            ]

        if len(last_message["content"]) > 0:
            # Only add cache_control to the last text block
            if isinstance(last_message["content"][-1], dict):
                last_message["content"][-1]["cache_control"] = {"type": "ephemeral"}
    return results


def _get_max_tokens_attempt_count(chat_history: list[MessageParam]) -> int:
    """Count how many max_tokens retry attempts have been made.

    Looks for the retry marker message in chat history.

    Returns:
        Number of previous attempts (0 if none)
    """
    marker = "[MAX_TOKENS_RETRY]"
    for msg in reversed(chat_history):
        if msg["role"] == "user":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if marker in text:
                            # Count [X] markers
                            return text.count("[X]")
            elif isinstance(content, str) and marker in content:
                return content.count("[X]")
    return 0


def _create_max_tokens_retry_message(attempt: int) -> MessageParam:
    """Create a user message instructing the agent to retry more concisely.

    Args:
        attempt: Which attempt this is (1, 2, or 3)

    Returns:
        A user message with retry instructions
    """
    marker = "[MAX_TOKENS_RETRY]"
    return {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": f"{marker} Your previous response was cut off because it hit the max token limit. "
                f"Please continue from where you left off, but be more concise. "
                f"Attempt {attempt} of 3: " + "[X]" * attempt,
            }
        ],
    }


async def _initialize_mcp(
    agent_context: "AgentContext",
    user_interface,
) -> tuple["MCPToolManager | None", bool]:
    """Initialize MCP servers if configured.

    Loads MCP configuration from global, persona, and project paths,
    connects to enabled servers, and returns the manager.

    Args:
        agent_context: Agent context with persona/project info
        user_interface: UI for status messages

    Returns:
        Tuple of (MCPToolManager or None, whether we own cleanup)
    """
    import logging

    logger = logging.getLogger(__name__)

    # Suppress MCP SDK's noisy warnings about non-JSON lines from server stdout
    # Some MCP servers (e.g., @isaacphi/mcp-gdrive) incorrectly print log messages
    # to stdout instead of stderr, causing benign parse errors
    logging.getLogger("mcp.client.stdio").setLevel(logging.ERROR)

    try:
        # Determine persona name from history_base_dir
        persona_name = None
        if agent_context.history_base_dir:
            # Extract persona name from path like ~/.silica/personas/{persona_name}
            history_path = Path(agent_context.history_base_dir)
            if history_path.parent.name == "personas":
                persona_name = history_path.name

        # Get project root from working directory
        project_root = Path.cwd()

        # Load merged config (function handles path construction internally)
        config = load_mcp_config(
            project_root=project_root,
            persona=persona_name,
        )

        if not config or not config.servers:
            logger.debug("No MCP servers configured")
            return None, False

        enabled_servers = config.get_enabled_servers()
        if not enabled_servers:
            logger.debug("No MCP servers enabled")
            return None, False

        # Create and connect manager
        manager = MCPToolManager()
        user_interface.handle_system_message(
            f"[dim]Connecting to {len(enabled_servers)} MCP server(s)...[/dim]",
            markdown=False,
        )

        results = await manager.connect_servers(config)

        # Report connection results
        connected = [name for name, err in results.items() if err is None]
        failed = [(name, err) for name, err in results.items() if err is not None]

        if connected:
            total_tools = sum(
                len(manager._clients[name].tools)
                for name in connected
                if name in manager._clients
            )
            user_interface.handle_system_message(
                f"[dim]MCP: Connected to {len(connected)} server(s) with {total_tools} tool(s)[/dim]",
                markdown=False,
            )

        if failed:
            for name, err in failed:
                user_interface.handle_system_message(
                    f"[yellow]MCP: Failed to connect to '{name}': {err}[/yellow]",
                    markdown=False,
                )

        return manager, True

    except Exception as e:
        logger.warning(f"Failed to initialize MCP: {e}")
        user_interface.handle_system_message(
            f"[yellow]MCP initialization failed: {e}[/yellow]",
            markdown=False,
        )
        return None, False


async def run(
    agent_context: AgentContext,
    initial_prompt: str = None,
    single_response: bool = False,
    tool_names: list[str] | None = None,
    tools: list | None = None,
    system_prompt: dict[str, Any] | None = None,
    enable_compaction: bool = True,
    log_file_path: str | None = None,
    mcp_manager: "MCPToolManager | None" = None,
) -> list[MessageParam]:
    load_dotenv()
    user_interface, model = (
        agent_context.user_interface,
        agent_context.model_spec,
    )

    # Initialize MCP if available and not provided
    mcp_manager_owned = False  # Track if we need to clean up the manager
    if mcp_manager is None and MCP_AVAILABLE:
        mcp_manager, mcp_manager_owned = await _initialize_mcp(
            agent_context, user_interface
        )

    # Create toolbox with either tools or tool_names (tools takes precedence)
    toolbox = Toolbox(
        agent_context, tool_names=tool_names, tools=tools, mcp_manager=mcp_manager
    )
    # Store toolbox reference on context so tools can access it
    agent_context.toolbox = toolbox
    if hasattr(user_interface, "set_toolbox"):
        user_interface.set_toolbox(toolbox)

    # Initialize request/response logger if enabled
    from silica.developer.request_logger import RequestResponseLogger

    logger = RequestResponseLogger(log_file_path)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        user_interface.handle_system_message(
            "[bold red]Error: ANTHROPIC_API_KEY environment variable not set[/bold red]",
            markdown=False,
        )
        return []

    client = anthropic.Client(api_key=api_key)
    rate_limiter = RateLimiter()

    interrupt_count = 0
    last_interrupt_time = 0
    return_to_user_after_interrupt = False

    # Initialize loop detector to catch repetitive tool calls
    loop_detector = LoopDetector(threshold=3)

    # Handle initial prompt if provided
    if initial_prompt:
        agent_context.chat_history.append(
            {"role": "user", "content": [{"type": "text", "text": initial_prompt}]}
        )
        user_interface.handle_user_input(
            f"[bold blue]You:[/bold blue] {initial_prompt}"
        )

    # Track when agent starts working (will be updated on each user input)
    agent_work_start_time = time.time()

    # Flag to skip user input prompt (e.g., after plan reminder injection)
    skip_user_input = False

    while True:
        try:
            if not skip_user_input and (
                return_to_user_after_interrupt
                or (
                    not agent_context.tool_result_buffer
                    and not single_response
                    and not initial_prompt
                )
            ):
                # Reset the interrupt flag
                return_to_user_after_interrupt = False

                user_input = ""
                while not user_input.strip():
                    # Build prompt inside loop so it updates when thinking mode changes
                    cost = f"${agent_context.usage_summary()['total_cost']:.2f}"
                    prompt = f"{cost} > "
                    if agent_context.thinking_mode == "normal":
                        prompt = f"💭 {cost} > "
                    elif agent_context.thinking_mode == "ultra":
                        prompt = f"🧠 {cost} > "

                    # Add plan mode indicator if active
                    try:
                        from silica.developer.tools.planning import (
                            get_active_plan_status,
                        )

                        plan_status = get_active_plan_status(agent_context)
                        if plan_status:
                            if plan_status["status"] == "planning":
                                prompt = f"📋 {prompt}"
                            elif plan_status["status"] == "executing":
                                # Show verified/total for progress
                                verified = plan_status.get("verified_tasks", 0)
                                total = plan_status["total_tasks"]
                                if total > 0:
                                    prompt = f"🚀 [{verified}✓/{total}] {prompt}"
                                else:
                                    prompt = f"🚀 {prompt}"
                    except Exception:
                        pass  # Don't fail if planning module has issues

                    user_input = await user_interface.get_user_input(prompt)

                # Track when user input was received to measure agent work duration
                agent_work_start_time = time.time()

                # Reset loop detector when user provides new input
                loop_detector.reset()

                command_name = (
                    user_input.split()[0][1:] if user_input.startswith("/") else ""
                )

                if user_input.startswith("/"):
                    if user_input in ["/quit", "/exit"]:
                        break
                    elif user_input in ["/restart", "/new", "/clear", "/reset"]:
                        # Clear the chat history and tool result buffer in the context
                        # Clear the context state and generate a new session ID
                        agent_context.chat_history.clear()
                        agent_context.tool_result_buffer.clear()
                        # Generate a new session ID for the agent context
                        agent_context.session_id = str(uuid4())
                        # Ensure we flush the cleared context to disk before continuing
                        agent_context.flush(agent_context.chat_history, compact=False)
                        user_interface.handle_system_message(
                            "[bold green]Chat history cleared and new session started.[/bold green]",
                            markdown=False,
                        )
                    elif command_name in toolbox.local:
                        tool = toolbox.local.get(command_name)
                        if tool:
                            result, append = await toolbox.invoke_cli_tool(
                                name=command_name,
                                arg_str=user_input[len(command_name) + 1 :].strip(),
                                chat_history=agent_context.chat_history,
                            )
                            if result and append:
                                agent_context.tool_result_buffer.append(
                                    {"type": "text", "text": result}
                                )
                    else:
                        user_interface.handle_system_message(
                            f"[bold red]Unknown command: {user_input}[/bold red]",
                            markdown=False,
                        )
                    continue

                agent_context.chat_history.append(
                    {"role": "user", "content": [{"type": "text", "text": user_input}]}
                )
                user_interface.handle_user_input(
                    f"[bold blue]You:[/bold blue] {user_input}"
                )

            elif (
                agent_context.chat_history
                and agent_context.chat_history[-1]["role"] == "user"
                and not agent_context.tool_result_buffer
            ):
                # User message exists with no tool results - proceed to AI generation
                # Reset skip flag now that we've used it
                skip_user_input = False
            else:
                if agent_context.tool_result_buffer:
                    agent_context.chat_history.append(
                        {
                            "role": "user",
                            "content": agent_context.tool_result_buffer.copy(),
                        }
                    )
                    agent_context.tool_result_buffer.clear()
                    agent_context.flush(
                        agent_context.chat_history,
                        compact=False,  # Compaction handled explicitly below
                    )

                # Check for compaction after tool results are converted to messages
                # This ensures we have the complete conversation state including tool interactions
                from silica.developer.compacter import ConversationCompacter

                compacter = ConversationCompacter(client=client, logger=logger)
                agent_context, _ = compacter.check_and_apply_compaction(
                    agent_context, model["title"], user_interface, enable_compaction
                )

                initial_prompt = None

            system_message = create_system_message(
                agent_context, system_section=system_prompt
            )
            ai_response = ""
            with user_interface.status(
                "[bold green]thinking...[/bold green]", spinner="dots"
            ):
                max_retries = 5
                base_delay = 1
                max_delay = 60

                for attempt in range(max_retries):
                    try:
                        await rate_limiter.check_and_wait(user_interface)

                        # Calculate conversation size before sending the next request
                        # This ensures we have a complete conversation state for accurate counting
                        conversation_size_for_display = None
                        context_window_for_display = None
                        if enable_compaction and not agent_context.tool_result_buffer:
                            try:
                                from silica.developer.compacter import (
                                    ConversationCompacter,
                                )

                                compacter = ConversationCompacter(
                                    client=client, logger=logger
                                )
                                model_name = model["title"]

                                # Check if conversation has incomplete tool_use before counting tokens
                                # This prevents the "tool_use ids found without tool_result blocks" error
                                if compacter._has_incomplete_tool_use(
                                    agent_context.chat_history
                                ):
                                    # Skip token counting for incomplete states
                                    pass
                                else:
                                    # Get context window size for this model
                                    context_window_for_display = (
                                        compacter.model_context_windows.get(
                                            model_name, 100000
                                        )
                                    )

                                    # Count tokens for complete conversation
                                    conversation_size_for_display = (
                                        compacter.count_tokens(
                                            agent_context, model_name
                                        )
                                    )

                                # Store for later display
                                agent_context._last_conversation_size = (
                                    conversation_size_for_display
                                )
                                agent_context._last_context_window = (
                                    context_window_for_display
                                )

                            except Exception as e:
                                print(f"Error calculating conversation size: {e}")

                        # Clean up any orphaned tool blocks before making the API call
                        # This handles cases where the conversation got into an invalid state
                        # (e.g., after max_tokens, crashes, or corrupted session loads)
                        from silica.developer.compaction_validation import (
                            strip_orphaned_tool_blocks,
                            validate_message_structure,
                        )

                        cleaned_history = strip_orphaned_tool_blocks(
                            agent_context.chat_history
                        )

                        # Check if cleanup made any changes
                        original_report = validate_message_structure(
                            agent_context.chat_history
                        )
                        cleaned_report = validate_message_structure(cleaned_history)
                        history_changed = (
                            len(cleaned_history) != len(agent_context.chat_history)
                            or not original_report.is_valid
                        )

                        if history_changed:
                            if len(cleaned_history) != len(agent_context.chat_history):
                                user_interface.handle_system_message(
                                    f"[yellow]Cleaned up orphaned tool blocks: "
                                    f"{len(agent_context.chat_history)} → {len(cleaned_history)} messages[/yellow]",
                                    markdown=False,
                                )
                            elif (
                                not original_report.is_valid and cleaned_report.is_valid
                            ):
                                user_interface.handle_system_message(
                                    "[yellow]Repaired invalid tool block pairing[/yellow]",
                                    markdown=False,
                                )

                        # Always use cleaned history (it's a no-op if nothing changed)
                        agent_context._chat_history = cleaned_history
                        agent_context.flush(agent_context.chat_history, compact=False)

                        messages = _process_file_mentions(
                            agent_context.chat_history, agent_context
                        )

                        # Get thinking configuration if enabled
                        thinking_config = get_thinking_config(
                            agent_context.thinking_mode, model
                        )

                        # Calculate max_tokens based on whether thinking is enabled
                        # When thinking is enabled, max_tokens must be thinking_budget + completion_tokens
                        max_tokens = model["max_tokens"]
                        if thinking_config and thinking_config.get("type") == "enabled":
                            max_tokens = (
                                thinking_config["budget_tokens"] + model["max_tokens"]
                            )

                        api_kwargs = {
                            "system": system_message,
                            "max_tokens": max_tokens,
                            "messages": messages,
                            "model": model["title"],
                            "tools": toolbox.agent_schema,
                        }

                        # Add thinking parameter if configured
                        if thinking_config:
                            api_kwargs["thinking"] = thinking_config

                        # Log the request
                        logger.log_request(
                            messages=messages,
                            system_message=system_message,
                            model=model["title"],
                            max_tokens=max_tokens,
                            tools=toolbox.agent_schema,
                            thinking_config=thinking_config,
                        )

                        thinking_content = ""
                        try:
                            with client.messages.stream(**api_kwargs) as stream:
                                for chunk in stream:
                                    if chunk.type == "text":
                                        ai_response += chunk.text
                                    elif chunk.type == "content_block_start":
                                        # Check if this is a thinking block
                                        if hasattr(chunk, "content_block") and hasattr(
                                            chunk.content_block, "type"
                                        ):
                                            if chunk.content_block.type == "thinking":
                                                thinking_content = ""
                                    elif chunk.type == "content_block_delta":
                                        # Accumulate thinking content if this is a thinking delta
                                        if hasattr(chunk, "delta") and hasattr(
                                            chunk.delta, "type"
                                        ):
                                            if chunk.delta.type == "thinking_delta":
                                                thinking_content += chunk.delta.thinking

                                final_message = stream.get_final_message()

                            # Log the response
                            logger.log_response(
                                message=final_message,
                                usage=final_message.usage,
                                stop_reason=final_message.stop_reason,
                                thinking_content=thinking_content
                                if thinking_content
                                else None,
                            )

                            rate_limiter.update(stream.response.headers)
                            break
                        except (
                            httpx.RemoteProtocolError,
                            httpx.ReadError,
                            httpx.ConnectError,
                            httpx.NetworkError,
                        ) as e:
                            # Handle network/connection errors during streaming
                            logger.log_error(
                                error_type=type(e).__name__,
                                error_message=str(e),
                                context={
                                    "attempt": attempt + 1,
                                    "max_retries": max_retries,
                                },
                            )

                            if attempt == max_retries - 1:
                                user_interface.handle_system_message(
                                    f"[bold red]Network error during streaming: {str(e)}. Max retries reached.[/bold red]",
                                    markdown=False,
                                )
                                raise

                            delay = min(
                                base_delay * (2**attempt) + random.uniform(0, 1),
                                max_delay,
                            )
                            user_interface.handle_system_message(
                                f"[bold yellow]Network error during streaming. Retrying in {delay:.2f} seconds... (Attempt {attempt + 1}/{max_retries})[/bold yellow]",
                                markdown=False,
                            )
                            time.sleep(delay)
                            # Clear partial response before retrying
                            ai_response = ""
                            thinking_content = ""
                            continue
                        except anthropic.APIStatusError as e:
                            # Handle API errors during streaming (e.g., overloaded mid-stream, server errors)
                            status_code = getattr(e, "status_code", None)
                            logger.log_error(
                                error_type="APIStatusError",
                                error_message=str(e),
                                context={
                                    "attempt": attempt + 1,
                                    "max_retries": max_retries,
                                    "status_code": status_code,
                                    "during_streaming": True,
                                },
                            )

                            if attempt == max_retries - 1:
                                user_interface.handle_system_message(
                                    f"[bold red]API error during streaming: {str(e)}. Max retries reached.[/bold red]",
                                    markdown=False,
                                )
                                raise

                            # Retry on overloaded (529) or internal server errors (500, 503)
                            is_retryable = (
                                "Overloaded" in str(e)
                                or "overloaded" in str(e).lower()
                                or status_code in [500, 503, 529]
                                or "internal server error" in str(e).lower()
                            )
                            if is_retryable:
                                delay = min(
                                    base_delay * (2**attempt) + random.uniform(0, 1),
                                    max_delay,
                                )
                                error_desc = (
                                    "API overloaded"
                                    if "overloaded" in str(e).lower()
                                    else f"Server error (status {status_code})"
                                )
                                user_interface.handle_system_message(
                                    f"[bold yellow]{error_desc} during streaming. Retrying in {delay:.2f} seconds... (Attempt {attempt + 1}/{max_retries})[/bold yellow]",
                                    markdown=False,
                                )
                                time.sleep(delay)
                                # Clear partial response before retrying
                                ai_response = ""
                                thinking_content = ""
                                continue
                            else:
                                # For non-retryable API errors, re-raise
                                raise
                    except anthropic.RateLimitError as e:
                        # Handle rate limit errors specifically
                        backoff_time = rate_limiter.handle_rate_limit_error(e)

                        # Log the error
                        logger.log_error(
                            error_type="RateLimitError",
                            error_message=str(e),
                            context={
                                "attempt": attempt + 1,
                                "max_retries": max_retries,
                                "backoff_time": backoff_time,
                            },
                        )

                        if attempt == max_retries - 1:
                            user_interface.handle_system_message(
                                "[bold red]Rate limit exceeded. Max retries reached. Please try again later.[/bold red]",
                                markdown=False,
                            )
                            raise

                        user_interface.handle_system_message(
                            f"[bold yellow]Rate limit exceeded. Retrying in {backoff_time:.2f} seconds... (Attempt {attempt + 1}/{max_retries})[/bold yellow]",
                            markdown=False,
                        )
                        # Wait time is already set in handle_rate_limit_error
                        continue

                    except anthropic.APIStatusError as e:
                        rate_limiter.update(e.response.headers)

                        status_code = getattr(e, "status_code", None)

                        # Log the error
                        logger.log_error(
                            error_type="APIStatusError",
                            error_message=str(e),
                            context={
                                "attempt": attempt + 1,
                                "max_retries": max_retries,
                                "status_code": status_code,
                            },
                        )

                        if attempt == max_retries - 1:
                            raise

                        # Retry on overloaded (529) or internal server errors (500, 503)
                        is_retryable = (
                            "Overloaded" in str(e)
                            or "overloaded" in str(e).lower()
                            or status_code in [500, 503, 529]
                            or "internal server error" in str(e).lower()
                        )
                        if is_retryable:
                            delay = min(
                                base_delay * (2**attempt) + random.uniform(0, 1),
                                max_delay,
                            )
                            error_desc = (
                                "API overloaded"
                                if "overloaded" in str(e).lower()
                                else f"Server error (status {status_code})"
                            )
                            user_interface.handle_system_message(
                                f"{error_desc}. Retrying in {delay:.2f} seconds...",
                                markdown=False,
                            )
                            time.sleep(delay)
                        else:
                            raise

            final_content = final_message.content
            filtered = []
            if isinstance(final_content, list):
                for message in final_content:
                    if isinstance(message, TextBlock):
                        message.text = message.text.strip()
                        if not message.text:
                            continue
                    filtered.append(message)
            else:
                filtered = final_content

            agent_context.chat_history.append(
                {"role": "assistant", "content": filtered}
            )

            agent_context.report_usage(final_message.usage)
            usage_summary = agent_context.usage_summary()

            # Display thinking content if present
            if thinking_content:
                thinking_tokens = usage_summary.get("total_thinking_tokens", 0)
                thinking_cost = usage_summary.get("thinking_cost", 0.0)
                if hasattr(user_interface, "handle_thinking_content"):
                    user_interface.handle_thinking_content(
                        thinking_content, thinking_tokens, thinking_cost, collapsed=True
                    )

            user_interface.handle_assistant_message(ai_response)

            # Use conversation size calculated before the API call (when state was complete)
            # This avoids counting incomplete states with tool_use but no tool_result
            conversation_size = getattr(agent_context, "_last_conversation_size", None)
            context_window = getattr(agent_context, "_last_context_window", None)

            # Calculate elapsed time since user input
            elapsed_seconds = time.time() - agent_work_start_time

            # Get active plan status for token summary display
            plan_slug = None
            plan_tasks_completed = None
            plan_tasks_verified = None
            plan_tasks_total = None
            try:
                from silica.developer.tools.planning import get_active_plan_status

                plan_status = get_active_plan_status(agent_context)
                if plan_status and plan_status.get("status") == "executing":
                    plan_slug = plan_status.get("slug")
                    total = plan_status.get("total_tasks", 0)
                    incomplete = plan_status.get("incomplete_tasks", 0)
                    plan_tasks_completed = total - incomplete
                    plan_tasks_verified = plan_status.get("verified_tasks", 0)
                    plan_tasks_total = total
            except Exception:
                pass  # Don't fail token display if plan status fails

            user_interface.display_token_count(
                usage_summary["total_input_tokens"],
                usage_summary["total_output_tokens"],
                usage_summary["total_input_tokens"]
                + usage_summary["total_output_tokens"],
                usage_summary["total_cost"],
                cached_tokens=usage_summary["cached_tokens"],
                conversation_size=conversation_size,
                context_window=context_window,
                thinking_tokens=usage_summary.get("total_thinking_tokens", 0),
                thinking_cost=usage_summary.get("thinking_cost", 0.0),
                elapsed_seconds=elapsed_seconds,
                plan_slug=plan_slug,
                plan_tasks_completed=plan_tasks_completed,
                plan_tasks_verified=plan_tasks_verified,
                plan_tasks_total=plan_tasks_total,
            )

            if final_message.stop_reason == "tool_use":
                tool_uses = [
                    part for part in final_message.content if part.type == "tool_use"
                ]
                if len(tool_uses) > 1:
                    agent_context.user_interface.handle_system_message(
                        f"Found {len(tool_uses)} tools"
                    )

                # Process all tool uses, potentially in parallel
                try:
                    results = await toolbox.invoke_agent_tools(tool_uses)

                    # Add all results to buffer and display them
                    modified_files = []
                    loop_detected = False
                    for tool_use, result in zip(tool_uses, results):
                        tool_name = getattr(tool_use, "name", "unknown_tool")
                        tool_use_id = getattr(tool_use, "id", None)
                        tool_input = getattr(tool_use, "input", {})

                        # Track modified files for plan task hints
                        if tool_name in ("write_file", "edit_file"):
                            if "path" in tool_input:
                                modified_files.append(tool_input["path"])

                        # Log tool execution
                        logger.log_tool_execution(
                            tool_name=tool_name,
                            tool_input=tool_input,
                            tool_result=result,
                        )

                        # Check if result is too large and would overflow context
                        from silica.developer.tool_result_limit import (
                            check_and_limit_result,
                        )

                        result, was_truncated = check_and_limit_result(
                            result, tool_name
                        )
                        if was_truncated:
                            original_tokens = result.get("_original_tokens", 0)
                            user_interface.handle_system_message(
                                f"[bold yellow]Tool result truncated: ~{original_tokens:,} tokens exceeded limit[/bold yellow]",
                                markdown=False,
                            )

                        agent_context.tool_result_buffer.append(result)
                        user_interface.handle_tool_result(
                            tool_name, result, tool_use_id=tool_use_id
                        )

                        # Check for repetitive loops
                        # Extract result content as string for comparison
                        result_content = result.get("content", "")
                        if isinstance(result_content, list):
                            # Handle list of content blocks
                            result_content = "".join(
                                c.get("text", str(c))
                                for c in result_content
                                if isinstance(c, dict)
                            )
                        elif not isinstance(result_content, str):
                            result_content = str(result_content)

                        if loop_detector.record_call(
                            tool_name, tool_input, result_content
                        ):
                            loop_detected = True

                    # If loop detected, inject intervention message
                    if loop_detected:
                        intervention_msg = loop_detector.get_intervention_message()
                        user_interface.handle_system_message(
                            f"[bold yellow]{intervention_msg}[/bold yellow]",
                            markdown=False,
                        )
                        # Add intervention as a user message to the tool result buffer
                        # This will be included in the next request to help break the loop
                        agent_context.tool_result_buffer.append(
                            {
                                "type": "text",
                                "text": intervention_msg,
                            }
                        )

                    # Note: Plan state reminders are now injected after assistant
                    # responses with no tool_use (see else branch below)
                except KeyboardInterrupt:
                    # Handle Ctrl+C during tool execution
                    user_interface.handle_system_message(
                        "[bold yellow]Tool execution interrupted by user (Ctrl+C)[/bold yellow]",
                        markdown=False,
                    )

                    # Create cancelled results for all tool uses - these MUST be added to chat history
                    # because the API requires every tool_use to have a corresponding tool_result
                    cancelled_results = []
                    for tool_use in tool_uses:
                        tool_use_id = getattr(tool_use, "id", "unknown_id")
                        result = {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": "cancelled",
                        }
                        cancelled_results.append(result)
                        tool_name = getattr(tool_use, "name", "unknown_tool")
                        user_interface.handle_tool_result(
                            tool_name, result, tool_use_id=tool_use_id
                        )

                    # Add cancelled results to chat history to satisfy API requirements
                    # Every tool_use must have a corresponding tool_result
                    agent_context.chat_history.append(
                        {
                            "role": "user",
                            "content": cancelled_results,
                        }
                    )
                    agent_context.flush(
                        agent_context.chat_history,
                        compact=False,
                    )

                    # Show a message that control is returning to user
                    user_interface.handle_system_message(
                        "[bold green]Control returned to user. You can now enter a new command.[/bold green]",
                        markdown=False,
                    )

                    # Set flag to force return to user input on next iteration
                    return_to_user_after_interrupt = True

                    # Continue to next iteration to return control to user
                    continue
                except DoSomethingElseError:
                    # Handle "do something else" workflow:
                    # 1. Remove the last assistant message
                    if (
                        agent_context.chat_history
                        and agent_context.chat_history[-1]["role"] == "assistant"
                    ):
                        agent_context.chat_history.pop()

                    # 2. Get user's alternate prompt
                    user_interface.handle_system_message(
                        "You selected 'do something else'. Please enter what you'd like to do instead:",
                        markdown=False,
                    )
                    alternate_prompt = await user_interface.get_user_input()

                    # 3. Append alternate prompt to the last user message
                    for i in reversed(range(len(agent_context.chat_history))):
                        if agent_context.chat_history[i]["role"] == "user":
                            # Add the alternate prompt to the previous user message
                            if isinstance(
                                agent_context.chat_history[i]["content"], str
                            ):
                                agent_context.chat_history[i]["content"] += (
                                    f"\n\nI viewed your response, and have updated my instructions: {alternate_prompt}"
                                )
                            elif isinstance(
                                agent_context.chat_history[i]["content"], list
                            ):
                                # Handle content as list of blocks
                                agent_context.chat_history[i]["content"].append(
                                    {
                                        "type": "text",
                                        "text": f"I viewed your response, and have updated my instructions: {alternate_prompt}",
                                    }
                                )
                            break

                    # Clear the tool result buffer to avoid processing the current tool request
                    agent_context.tool_result_buffer.clear()

                    # Skip to the next iteration to immediately process the updated chat history
                    # instead of breaking out of the loop which would wait for next user input
                    continue
                except Exception as e:
                    # Handle any other exceptions during tool batch invocation
                    error_message = f"Error invoking tools: {str(e)}"
                    user_interface.handle_system_message(
                        f"[bold red]{error_message}[/bold red]", markdown=False
                    )
                    # Add error results for all tools
                    for tool_use in tool_uses:
                        tool_use_id = getattr(tool_use, "id", "unknown_id")
                        result = {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": error_message,
                            "is_error": True,
                        }
                        agent_context.tool_result_buffer.append(result)
                        user_interface.handle_tool_result(
                            getattr(tool_use, "name", "unknown_tool"),
                            result,
                            tool_use_id=tool_use_id,
                        )
            elif final_message.stop_reason == "max_tokens":
                # Response was truncated - we need to signal the agent to continue
                # but more concisely

                # Count previous retry attempts
                attempt_count = _get_max_tokens_attempt_count(
                    agent_context.chat_history
                )

                if attempt_count >= 3:
                    # Already tried 3 times, give up
                    user_interface.handle_system_message(
                        "[bold yellow]Hit max tokens. Was unable to continue after multiple attempts.[/bold yellow]",
                        markdown=False,
                    )
                    # Keep the partial response in history so user can see what was generated
                    # Don't continue the loop - return to user
                else:
                    # Can retry - add a new user message with retry instructions
                    attempt_count += 1
                    user_interface.handle_system_message(
                        f"[bold yellow]Hit max tokens (attempt {attempt_count}/3). Continuing...[/bold yellow]",
                        markdown=False,
                    )

                    # Add retry message as a NEW user message
                    # This ensures the agent sees the instruction clearly
                    retry_msg = _create_max_tokens_retry_message(attempt_count)
                    agent_context.chat_history.append(retry_msg)

                    # Continue the loop to retry the API call
                    continue

            else:
                # Check if we should inject a plan reminder to keep the agent working
                # This happens when the agent responds without tool_use but has an
                # incomplete plan - we nudge it to continue instead of returning to user
                should_inject, plan_state = _should_inject_plan_reminder(agent_context)
                if should_inject and plan_state:
                    user_interface.handle_system_message(
                        "[dim]Plan in progress - nudging agent to continue...[/dim]",
                        markdown=False,
                    )
                    # Add plan reminder as a user message and continue the loop
                    # Note: Don't add cache_control here - _process_file_mentions will add it
                    # to the last text block, and we must stay under the 4 block limit
                    agent_context.chat_history.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": plan_state,
                                }
                            ],
                        }
                    )
                    # Skip user input on next iteration - we just injected a message
                    skip_user_input = True
                    # Continue the loop to give the agent another chance
                    continue

            interrupt_count = 0
            last_interrupt_time = 0

            # Exit after one response if in single-response mode
            if single_response and not agent_context.tool_result_buffer:
                agent_context.flush(
                    _process_file_mentions(agent_context.chat_history, agent_context),
                    compact=False,  # Compaction handled explicitly above
                )
                break

        except KeyboardInterrupt:
            current_time = time.time()
            if current_time - last_interrupt_time < 1:
                interrupt_count += 1
            else:
                interrupt_count = 1
            last_interrupt_time = current_time

            if interrupt_count >= 2:
                user_interface.handle_system_message(
                    "[bold red]Exiting...[/bold red]",
                    markdown=False,
                )
                # Clean exit - break from loop to allow proper cleanup
                break
            else:
                user_interface.handle_system_message(
                    "[bold yellow]"
                    "Interrupted. Press Ctrl+C again within 1 second to exit, or press Enter to continue."
                    "[/bold yellow]",
                    markdown=False,
                )
        finally:
            # Flush without compaction - compaction is handled explicitly in the main loop
            agent_context.flush(agent_context.chat_history, compact=False)

    # Clean up MCP connections if we own the manager
    if mcp_manager_owned and mcp_manager is not None:
        try:
            await mcp_manager.disconnect_all()
            user_interface.handle_system_message(
                "[dim]MCP: Disconnected from all servers[/dim]",
                markdown=False,
            )
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(f"Error disconnecting MCP servers: {e}")

    return agent_context.chat_history
