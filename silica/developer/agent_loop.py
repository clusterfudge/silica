import copy
import os
import time
import random
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import anthropic
from anthropic.types import TextBlock, MessageParam
from dotenv import load_dotenv

from silica.developer.context import AgentContext
from silica.developer.prompt import create_system_message
from silica.developer.rate_limiter import RateLimiter
from silica.developer.toolbox import Toolbox
from silica.developer.sandbox import DoSomethingElseError


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


def _inline_latest_file_mentions(
    chat_history: list[MessageParam],
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

    # HACK: we just happen to be seeing messages go past, so we'll handle cache_control here.
    # Add cache_control to the last text block in a user message, ensuring all content is list-type
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


def _apply_compaction_transition(
    agent_context: AgentContext, transition
) -> AgentContext:
    """Apply a compaction transition to the agent context.

    Args:
        agent_context: The current agent context
        transition: CompactionTransition object with new session info

    Returns:
        Updated agent context with compacted conversation
    """
    # Update session IDs to reflect the transition
    agent_context.parent_session_id = transition.original_session_id
    agent_context.session_id = transition.new_session_id

    # Replace chat history with compacted version
    agent_context._chat_history = transition.compacted_messages.copy()

    # Clear tool result buffer for clean state
    agent_context.tool_result_buffer.clear()

    return agent_context


def _check_and_apply_compaction(
    agent_context: AgentContext,
    model: dict,
    user_interface,
    enable_compaction: bool = True,
) -> tuple[AgentContext, bool]:
    """Check if compaction is needed and apply it if necessary.

    Args:
        agent_context: The agent context to check
        model: Model specification dict
        user_interface: User interface for notifications
        enable_compaction: Whether compaction is enabled

    Returns:
        Tuple of (possibly updated agent_context, True if compaction was applied)
    """
    if not enable_compaction:
        return agent_context, False

    # Only check compaction when conversation state is complete
    # (no pending tool results and conversation has actual content)
    if (
        agent_context.tool_result_buffer
        or not agent_context.chat_history
        or len(agent_context.chat_history) <= 2
    ):
        return agent_context, False

    try:
        from silica.developer.compacter import ConversationCompacter

        compacter = ConversationCompacter()
        model_name = model["title"]

        transition = compacter.compact_and_transition(agent_context, model_name)

        if transition:
            # Apply the transition to start using the compacted conversation
            updated_context = _apply_compaction_transition(agent_context, transition)

            # Notify user about the compaction and transition
            user_interface.handle_system_message(
                f"[bold green]Conversation compacted: "
                f"{transition.summary.original_message_count} messages → "
                f"new session {transition.new_session_id[:8]}[/bold green]",
                markdown=False,
            )

            # Save both sessions: original (already saved) and new compacted one
            updated_context.flush(updated_context.chat_history, compact=False)
            return updated_context, True

    except Exception as e:
        # Log compaction errors but continue normally
        user_interface.handle_system_message(
            f"[yellow]Compaction check failed: {e}[/yellow]",
            markdown=False,
        )

    return agent_context, False


def _continuation_message(final_message: MessageParam) -> MessageParam | None:
    continue_message = {
        "type": "text",
        "text": "In a previous attempt, you hit max tokens. Please try to be more concise. Attempts of 3: ",
    }
    last_content_block = final_message["content"][-1]
    if last_content_block["type"] != "text" or not last_content_block[
        "text"
    ].startswith(continue_message["text"]):
        final_message["content"].append(continue_message)
    else:
        continue_message = final_message["content"][-1]

    continue_message["text"] += "[X]"
    if "[X][X][X]" in continue_message["text"]:
        return None  # we've already had 3 attempts, stop trying. :(

    return final_message


async def run(
    agent_context: AgentContext,
    initial_prompt: str = None,
    single_response: bool = False,
    tool_names: list[str] | None = None,
    system_prompt: dict[str, Any] | None = None,
    enable_compaction: bool = True,
) -> list[MessageParam]:
    load_dotenv()
    user_interface, model = (
        agent_context.user_interface,
        agent_context.model_spec,
    )
    toolbox = Toolbox(agent_context, tool_names=tool_names)
    if hasattr(user_interface, "set_toolbox"):
        user_interface.set_toolbox(toolbox)

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

    # Handle initial prompt if provided
    if initial_prompt:
        agent_context.chat_history.append(
            {"role": "user", "content": [{"type": "text", "text": initial_prompt}]}
        )
        user_interface.handle_user_input(
            f"[bold blue]You:[/bold blue] {initial_prompt}"
        )

    while True:
        try:
            # Check for compaction when conversation state is complete
            agent_context, _ = _check_and_apply_compaction(
                agent_context, model, user_interface, enable_compaction
            )

            if return_to_user_after_interrupt or (
                not agent_context.tool_result_buffer
                and not single_response
                and not initial_prompt
            ):
                # Reset the interrupt flag
                return_to_user_after_interrupt = False
                cost = f"${agent_context.usage_summary()['total_cost']:.2f}"
                user_input = ""
                while not user_input.strip():
                    user_input = await user_interface.get_user_input(f"{cost} > ")

                command_name = (
                    user_input.split()[0][1:] if user_input.startswith("/") else ""
                )

                if user_input.startswith("/"):
                    if user_input in ["/quit", "/exit"]:
                        break
                    elif user_input == "/restart":
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
                pass
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
                        compact=False,  # Compaction handled explicitly above
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

                        # Check for compaction before making API call - this is the critical timing
                        # where we can catch conversations that have grown too large
                        agent_context, compaction_applied = _check_and_apply_compaction(
                            agent_context, model, user_interface, enable_compaction
                        )
                        if compaction_applied:
                            # If compaction occurred, restart the API request attempt
                            # with the newly compacted conversation
                            continue

                        # Calculate conversation size before sending the next request
                        # This ensures we have a complete conversation state for accurate counting
                        conversation_size_for_display = None
                        context_window_for_display = None
                        if enable_compaction and not agent_context.tool_result_buffer:
                            try:
                                from silica.developer.compacter import (
                                    ConversationCompacter,
                                )

                                compacter = ConversationCompacter()
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

                        messages = _inline_latest_file_mentions(
                            agent_context.chat_history
                        )
                        with client.messages.stream(
                            system=system_message,
                            max_tokens=model["max_tokens"],
                            messages=messages,
                            model=model["title"],
                            tools=toolbox.agent_schema,
                        ) as stream:
                            for chunk in stream:
                                if chunk.type == "text":
                                    ai_response += chunk.text

                            final_message = stream.get_final_message()

                        rate_limiter.update(stream.response.headers)
                        break
                    except anthropic.RateLimitError as e:
                        # Handle rate limit errors specifically
                        backoff_time = rate_limiter.handle_rate_limit_error(e)
                        if attempt == max_retries - 1:
                            user_interface.handle_system_message(
                                "[bold red]Rate limit exceeded. Max retries reached. Please try again later.[/bold red]",
                                markdown=False,
                            )
                            raise

                        user_interface.handle_system_message(
                            f"[bold yellow]Rate limit exceeded. Retrying in {backoff_time:.2f} seconds... (Attempt {attempt+1}/{max_retries})[/bold yellow]",
                            markdown=False,
                        )
                        # Wait time is already set in handle_rate_limit_error
                        continue

                    except anthropic.APIStatusError as e:
                        rate_limiter.update(e.response.headers)
                        if attempt == max_retries - 1:
                            raise
                        if "Overloaded" in str(e):
                            delay = min(
                                base_delay * (2**attempt) + random.uniform(0, 1),
                                max_delay,
                            )
                            user_interface.handle_system_message(
                                f"API overloaded. Retrying in {delay:.2f} seconds...",
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
            user_interface.handle_assistant_message(ai_response)

            # Use conversation size calculated before the API call (when state was complete)
            # This avoids counting incomplete states with tool_use but no tool_result
            conversation_size = getattr(agent_context, "_last_conversation_size", None)
            context_window = getattr(agent_context, "_last_context_window", None)

            user_interface.display_token_count(
                usage_summary["total_input_tokens"],
                usage_summary["total_output_tokens"],
                usage_summary["total_input_tokens"]
                + usage_summary["total_output_tokens"],
                usage_summary["total_cost"],
                cached_tokens=usage_summary["cached_tokens"],
                conversation_size=conversation_size,
                context_window=context_window,
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
                    for tool_use, result in zip(tool_uses, results):
                        tool_name = getattr(tool_use, "name", "unknown_tool")
                        agent_context.tool_result_buffer.append(result)
                        user_interface.handle_tool_result(tool_name, result)
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
                        result = {
                            "type": "tool_result",
                            "tool_use_id": getattr(tool_use, "id", "unknown_id"),
                            "content": "cancelled",
                        }
                        cancelled_results.append(result)
                        tool_name = getattr(tool_use, "name", "unknown_tool")
                        user_interface.handle_tool_result(tool_name, result)

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
                        result = {
                            "type": "tool_result",
                            "tool_use_id": getattr(tool_use, "id", "unknown_id"),
                            "content": error_message,
                        }
                        agent_context.tool_result_buffer.append(result)
                        user_interface.handle_tool_result(
                            getattr(tool_use, "name", "unknown_tool"), result
                        )
            elif final_message.stop_reason == "max_tokens":
                # Don't add the partial message to chat history (remove it if necessary)
                if (
                    agent_context.chat_history
                    and agent_context.chat_history[-1]["role"] == "assistant"
                ):
                    agent_context.chat_history.pop()

                retry_message = _continuation_message(agent_context.chat_history[-1])

                if retry_message:
                    user_interface.handle_assistant_message(
                        "[bold yellow]Hit max tokens. I'll continue from where I left off...[/bold yellow]"
                    )

                    agent_context.chat_history[len(agent_context.chat_history) - 2] = (
                        retry_message
                    )
                else:
                    user_interface.handle_assistant_message(
                        "[bold yellow]Hit max tokens. Was unable to continue after multiple attempts.[/bold yellow]"
                    )
                    agent_context.chat_history.pop()

            interrupt_count = 0
            last_interrupt_time = 0

            # Exit after one response if in single-response mode
            if single_response and not agent_context.tool_result_buffer:
                agent_context.flush(
                    _inline_latest_file_mentions(agent_context.chat_history),
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
                    "[bold red]Double interrupt detected. Exiting...[/bold red]",
                    markdown=False,
                )
                break
            else:
                user_interface.handle_system_message(
                    "[bold yellow]"
                    "KeyboardInterrupt detected. Press Ctrl+C again to exit, or continue typing to resume."
                    "[/bold yellow]",
                    markdown=False,
                )
        finally:
            # Flush without compaction - compaction is handled explicitly in the main loop
            agent_context.flush(agent_context.chat_history, compact=False)
    return agent_context.chat_history
