"""Tool result size limiting to prevent context window overflow.

When a tool result is too large, it can push the conversation past the context
window limit, causing the API call to fail. This module provides utilities to
detect and handle oversized tool results by replacing them with helpful error
messages that guide the agent to try a different approach.
"""

import os
from typing import Any

# Default maximum tokens per tool result (can be overridden via env var)
# This should be well below the context window to leave room for history
DEFAULT_MAX_TOOL_RESULT_TOKENS = 50000

# Minimum threshold - don't allow setting below this
MIN_TOOL_RESULT_TOKENS = 1000


def get_max_tool_result_tokens() -> int:
    """Get the maximum allowed tokens for a single tool result.

    Can be configured via SILICA_MAX_TOOL_RESULT_TOKENS environment variable.
    """
    env_value = os.getenv("SILICA_MAX_TOOL_RESULT_TOKENS")
    if env_value:
        try:
            value = int(env_value)
            if value >= MIN_TOOL_RESULT_TOKENS:
                return value
            else:
                print(
                    f"Warning: SILICA_MAX_TOOL_RESULT_TOKENS={value} is below minimum "
                    f"{MIN_TOOL_RESULT_TOKENS}, using default {DEFAULT_MAX_TOOL_RESULT_TOKENS}"
                )
        except ValueError:
            print(
                f"Warning: Invalid SILICA_MAX_TOOL_RESULT_TOKENS value '{env_value}', "
                f"using default {DEFAULT_MAX_TOOL_RESULT_TOKENS}"
            )
    return DEFAULT_MAX_TOOL_RESULT_TOKENS


def estimate_tokens(text: str) -> int:
    """Estimate token count for text using character-based heuristic.

    This is a fast approximation - roughly 4 characters per token for English.
    For base64 content it's closer to 3-4 chars per token.

    Args:
        text: The text to estimate tokens for

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    # Use conservative estimate of ~3.5 chars per token
    return len(text) // 3


def get_result_content_size(result: dict[str, Any]) -> tuple[int, str]:
    """Get the estimated token size and content type of a tool result.

    Args:
        result: Tool result dictionary with 'content' field

    Returns:
        Tuple of (estimated_tokens, content_description)
    """
    content = result.get("content", "")

    if isinstance(content, str):
        return estimate_tokens(content), "text"

    if isinstance(content, list):
        total_tokens = 0
        content_types = set()

        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type", "unknown")
                content_types.add(item_type)

                if item_type == "text":
                    total_tokens += estimate_tokens(item.get("text", ""))
                elif item_type == "image":
                    # Images sent as base64 can be huge
                    source = item.get("source", {})
                    if source.get("type") == "base64":
                        data = source.get("data", "")
                        total_tokens += estimate_tokens(data)
                    else:
                        # URL-based images are small
                        total_tokens += 100
                else:
                    # Unknown type - estimate based on str representation
                    total_tokens += estimate_tokens(str(item))
            elif isinstance(item, str):
                total_tokens += estimate_tokens(item)
                content_types.add("text")

        return total_tokens, "+".join(sorted(content_types)) or "mixed"

    # Fallback for other types
    return estimate_tokens(str(content)), "unknown"


def create_truncation_message(
    tool_name: str,
    original_tokens: int,
    max_tokens: int,
    content_type: str,
) -> str:
    """Create a helpful message explaining that the result was truncated.

    Args:
        tool_name: Name of the tool that produced the result
        original_tokens: Estimated tokens in the original result
        max_tokens: Maximum allowed tokens
        content_type: Type of content (text, image, etc.)

    Returns:
        A message explaining the truncation and suggesting alternatives
    """
    suggestions = []

    if content_type == "image" or "image" in content_type:
        suggestions.extend(
            [
                "- Use a smaller image or lower resolution",
                "- If reading a file, ensure it's a text file not binary/image data",
                "- Use a tool that returns a URL instead of raw image data",
            ]
        )
    elif "text" in content_type:
        suggestions.extend(
            [
                "- Read only a portion of the file (use line ranges if supported)",
                "- Use grep/search to find specific content instead of reading the whole file",
                "- Summarize or filter the output before returning",
                "- If this is binary data read as text, use an appropriate binary tool",
            ]
        )

    suggestions_text = (
        "\n".join(suggestions) if suggestions else "- Try a different approach"
    )

    return f"""TOOL RESULT TOO LARGE - The result from '{tool_name}' was truncated.

Estimated size: ~{original_tokens:,} tokens (limit: {max_tokens:,} tokens)
Content type: {content_type}

The result exceeded the maximum allowed size and could not be included in the
conversation. This protects against context window overflow errors.

Suggestions to get the information you need:
{suggestions_text}

Please try a different approach that produces smaller output."""


def check_and_limit_result(
    result: dict[str, Any],
    tool_name: str,
    max_tokens: int | None = None,
) -> tuple[dict[str, Any], bool]:
    """Check if a tool result exceeds the size limit and truncate if needed.

    Args:
        result: The tool result dictionary
        tool_name: Name of the tool (for error message)
        max_tokens: Maximum allowed tokens (uses default if not specified)

    Returns:
        Tuple of (result, was_truncated) where result may be modified
    """
    if max_tokens is None:
        max_tokens = get_max_tool_result_tokens()

    estimated_tokens, content_type = get_result_content_size(result)

    if estimated_tokens <= max_tokens:
        return result, False

    # Result is too large - replace with truncation message
    truncation_msg = create_truncation_message(
        tool_name=tool_name,
        original_tokens=estimated_tokens,
        max_tokens=max_tokens,
        content_type=content_type,
    )

    # Preserve the tool_use_id and other metadata, just replace content
    truncated_result = {
        **result,
        "content": truncation_msg,
        "is_error": True,  # Mark as error so agent knows to try something else
        "_truncated": True,  # Internal flag
        "_original_tokens": estimated_tokens,
    }

    return truncated_result, True


def check_context_overflow(
    agent_context,
    model_spec: dict[str, Any],
    pending_tool_results: list[dict[str, Any]] | None = None,
) -> tuple[bool, int, int]:
    """Check if the context (including pending tool results) would overflow.

    This is a pre-flight check before making an API call to detect if we'd
    exceed the context window. It's useful when tool results have been added
    but not yet committed to history, or after compaction when we want to
    verify we're under the limit.

    Args:
        agent_context: The agent context with chat history
        model_spec: Model specification dict with 'context_window' and 'title'
        pending_tool_results: Optional list of pending tool results to include

    Returns:
        Tuple of (would_overflow, estimated_tokens, context_window)
    """
    context_window = model_spec.get("context_window", 200000)

    # Estimate tokens for current history
    history_tokens = 0
    for message in agent_context.chat_history:
        content = message.get("content", "")
        if isinstance(content, str):
            history_tokens += estimate_tokens(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if "text" in item:
                        history_tokens += estimate_tokens(item["text"])
                    elif item.get("type") == "tool_result":
                        result_content = item.get("content", "")
                        if isinstance(result_content, str):
                            history_tokens += estimate_tokens(result_content)
                        elif isinstance(result_content, list):
                            for block in result_content:
                                if isinstance(block, dict) and "text" in block:
                                    history_tokens += estimate_tokens(block["text"])

    # Add pending tool results if provided
    pending_tokens = 0
    if pending_tool_results:
        for result in pending_tool_results:
            tokens, _ = get_result_content_size(result)
            pending_tokens += tokens

    # Estimate system prompt and tools overhead (rough estimate)
    # This varies by model and toolbox size, but typically 5-20K tokens
    overhead_tokens = 15000

    total_estimated = history_tokens + pending_tokens + overhead_tokens
    would_overflow = total_estimated > context_window

    return would_overflow, total_estimated, context_window


def create_context_overflow_message(
    estimated_tokens: int,
    context_window: int,
    tool_results_truncated: int = 0,
) -> str:
    """Create a message explaining context overflow to the agent.

    Args:
        estimated_tokens: Estimated total tokens
        context_window: Context window size
        tool_results_truncated: Number of tool results that were truncated

    Returns:
        Message explaining the situation and suggesting recovery steps
    """
    overflow_amount = estimated_tokens - context_window

    msg = f"""CONTEXT WINDOW OVERFLOW - Unable to proceed with current conversation.

Estimated tokens: ~{estimated_tokens:,}
Context window: {context_window:,}
Overflow by: ~{overflow_amount:,} tokens

"""

    if tool_results_truncated > 0:
        msg += f"{tool_results_truncated} tool result(s) were truncated but the conversation still exceeds the context limit.\n\n"

    msg += """Recovery options:
1. Use /restart to start a fresh conversation
2. The session history is preserved and can be referenced if needed
3. Consider breaking large tasks into smaller conversations

This typically happens when:
- A file or tool output was unexpectedly large
- The conversation accumulated many tool results over time
- Large base64-encoded data was accidentally read as text"""

    return msg
