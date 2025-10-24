#!/usr/bin/env python3
"""
Conversation compaction module for silica Developer.

This module provides functionality to compact long conversations by summarizing them
and starting a new conversation when they exceed certain token limits.
"""

import os
import json
from typing import List
from dataclasses import dataclass
import anthropic
from anthropic.types import MessageParam

from silica.developer.context import AgentContext
from silica.developer.models import model_names, get_model

# Default threshold ratio of model's context window to trigger compaction
DEFAULT_COMPACTION_THRESHOLD_RATIO = 0.80  # Trigger compaction at 80% of context window


@dataclass
class CompactionSummary:
    """Summary of a compacted conversation."""

    original_message_count: int
    original_token_count: int
    summary_token_count: int
    compaction_ratio: float
    summary: str


@dataclass
class CompactionMetadata:
    """Metadata about a compaction operation."""

    archive_name: str
    original_message_count: int
    compacted_message_count: int
    original_token_count: int
    summary_token_count: int
    compaction_ratio: float


class ConversationCompacter:
    """Handles the compaction of long conversations into summaries."""

    def __init__(
        self,
        client: anthropic.Client,
        threshold_ratio: float = DEFAULT_COMPACTION_THRESHOLD_RATIO,
        logger=None,
    ):
        """Initialize the conversation compacter.

        Args:
            client: Anthropic client instance (required)
            threshold_ratio: Ratio of model's context window to trigger compaction
            logger: RequestResponseLogger instance (optional, for logging API calls)
        """
        # Allow threshold to be configured via environment variable
        env_threshold = os.getenv("SILICA_COMPACTION_THRESHOLD")
        if env_threshold:
            try:
                threshold_ratio = float(env_threshold)
                if not 0.0 < threshold_ratio < 1.0:
                    print(
                        f"Warning: SILICA_COMPACTION_THRESHOLD must be between 0 and 1, "
                        f"got {threshold_ratio}. Using default {DEFAULT_COMPACTION_THRESHOLD_RATIO}"
                    )
                    threshold_ratio = DEFAULT_COMPACTION_THRESHOLD_RATIO
            except ValueError:
                print(
                    f"Warning: Invalid SILICA_COMPACTION_THRESHOLD value '{env_threshold}'. "
                    f"Using default {DEFAULT_COMPACTION_THRESHOLD_RATIO}"
                )
                threshold_ratio = DEFAULT_COMPACTION_THRESHOLD_RATIO

        self.threshold_ratio = threshold_ratio
        self.logger = logger
        self.client = client

        # Get model context window information
        self.model_context_windows = {
            model_data["title"]: model_data.get("context_window", 100000)
            for model_data in [get_model(ms) for ms in model_names()]
        }

    def count_tokens(self, agent_context, model: str) -> int:
        """Count tokens for the complete context sent to the API.

        This method accurately counts tokens for the complete API call including
        system prompt, tools, and messages - fixing HDEV-61.

        Args:
            agent_context: AgentContext instance to get full API context from
            model: Model name to use for token counting

        Returns:
            int: Number of tokens for the complete context
        """
        try:
            # Get the full context that would be sent to the API
            context_dict = agent_context.get_api_context()

            # Check if conversation has incomplete tool_use without tool_result
            # This would cause an API error, so use estimation instead
            if self._has_incomplete_tool_use(context_dict["messages"]):
                return self._estimate_full_context_tokens(context_dict)

            # Strip thinking blocks to avoid API complexity
            # Thinking blocks have complicated validation rules, so just remove them for counting
            messages_for_counting = self._strip_all_thinking_blocks(
                context_dict["messages"]
            )

            # Use the Anthropic API's count_tokens method
            count_kwargs = {
                "model": model,
                "system": context_dict["system"],
                "messages": messages_for_counting,
                "tools": context_dict["tools"] if context_dict["tools"] else None,
            }

            # Log the request if logger is available
            if self.logger:
                self.logger.log_request(
                    messages=messages_for_counting,
                    system_message=context_dict["system"],
                    model=model,
                    max_tokens=0,  # count_tokens doesn't use max_tokens
                    tools=context_dict["tools"] if context_dict["tools"] else [],
                    thinking_config=None,
                )

            response = self.client.messages.count_tokens(**count_kwargs)

            # Log the response if logger is available
            if self.logger:
                # count_tokens doesn't return a full message, so log what we have
                if hasattr(response, "token_count"):
                    token_count = response.token_count
                elif hasattr(response, "tokens"):
                    token_count = response.tokens
                elif isinstance(response, dict):
                    token_count = response.get("token_count", 0)
                else:
                    token_count = 0
                # Create a simplified response log entry
                from datetime import datetime
                import time

                log_entry = {
                    "type": "response",
                    "timestamp": datetime.now().isoformat(),
                    "unix_timestamp": time.time(),
                    "message_id": "count_tokens_response",
                    "stop_reason": "count_tokens",
                    "content": [
                        {"type": "text", "text": f"Token count: {token_count}"}
                    ],
                    "usage": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                }
                # Write directly to avoid needing the Message object
                self.logger._write_log_entry(log_entry)

            # Extract token count from response
            if hasattr(response, "token_count"):
                return response.token_count
            elif hasattr(response, "tokens"):
                return response.tokens
            else:
                # Handle dictionary response
                response_dict = (
                    response if isinstance(response, dict) else response.__dict__
                )
                if "token_count" in response_dict:
                    return response_dict["token_count"]
                elif "tokens" in response_dict:
                    return response_dict["tokens"]
                elif "input_tokens" in response_dict:
                    return response_dict["input_tokens"]
                else:
                    print(f"Token count not found in response: {response}")
                    return self._estimate_full_context_tokens(context_dict)

        except Exception as e:
            print(f"Error counting tokens for full context: {e}")
            # Fallback to estimation
            context_dict = agent_context.get_api_context()
            return self._estimate_full_context_tokens(context_dict)

    def _has_incomplete_tool_use(self, messages: list) -> bool:
        """Check if messages have tool_use without corresponding tool_result.

        Args:
            messages: List of messages to check

        Returns:
            bool: True if there are incomplete tool_use blocks
        """
        if not messages:
            return False

        last_message = messages[-1]
        if last_message.get("role") != "assistant":
            return False

        content = last_message.get("content", [])
        if not isinstance(content, list):
            return False

        # Check if last assistant message has tool_use
        return any(
            isinstance(block, dict) and block.get("type") == "tool_use"
            for block in content
        )

    def _strip_all_thinking_blocks(self, messages: list) -> list:
        """Strip ALL thinking blocks from ALL messages.

        This is used when the last assistant message doesn't start with thinking,
        but earlier messages have thinking blocks. The API requires that if ANY
        message has thinking, the thinking parameter must be enabled. But if
        thinking is enabled, the LAST message must start with thinking. So when
        the last message doesn't have thinking, we must strip ALL thinking blocks.

        Args:
            messages: List of messages that may contain thinking blocks

        Returns:
            Deep copy of messages with all thinking blocks stripped out
        """
        import copy

        # Deep copy to avoid modifying the original
        cleaned_messages = copy.deepcopy(messages)

        for message in cleaned_messages:
            if message.get("role") != "assistant":
                continue

            content = message.get("content", [])
            if not isinstance(content, list):
                continue

            # Filter out thinking blocks
            filtered_content = []
            for block in content:
                # Check both dict and object representations
                block_type = None
                if isinstance(block, dict):
                    block_type = block.get("type")
                elif hasattr(block, "type"):
                    block_type = block.type

                # Skip thinking and redacted_thinking blocks
                if block_type not in ["thinking", "redacted_thinking"]:
                    filtered_content.append(block)

            message["content"] = filtered_content

        return cleaned_messages

    def _estimate_full_context_tokens(self, context_dict: dict) -> int:
        """Estimate token count for full context as a fallback.

        Args:
            context_dict: Dict with 'system', 'tools', and 'messages' keys

        Returns:
            int: Estimated token count
        """
        total_chars = 0

        # Count system message characters
        if context_dict.get("system"):
            for block in context_dict["system"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    total_chars += len(block.get("text", ""))

        # Count tools characters
        if context_dict.get("tools"):
            import json

            total_chars += len(json.dumps(context_dict["tools"]))

        # Count messages characters
        if context_dict.get("messages"):
            messages_str = self._messages_to_string(
                context_dict["messages"], for_summary=False
            )
            total_chars += len(messages_str)

        # Rough estimate: 1 token per 3-4 characters for English text
        return int(total_chars / 3.5)

    def _messages_to_string(
        self, messages: List[MessageParam], for_summary: bool = False
    ) -> str:
        """Convert message objects to a string representation.

        Args:
            messages: List of messages in the conversation
            for_summary: If True, filter out content elements containing mentioned_file blocks

        Returns:
            str: String representation of the messages
        """
        conversation_str = ""

        for message in messages:
            role = message.get("role", "unknown")

            # Process content based on its type
            content = message.get("content", "")
            if isinstance(content, str):
                content_str = content
            elif isinstance(content, list):
                # Extract text from content blocks
                content_parts = []
                for item in content:
                    if isinstance(item, dict):
                        if "text" in item:
                            text = item["text"]
                            # If processing for summary, skip content blocks containing mentioned_file
                            if for_summary and "<mentioned_file" in text:
                                try:
                                    # Extract the path attribute from the mentioned_file tag
                                    import re

                                    match = re.search(
                                        r"<mentioned_file path=([^ >]+)", text
                                    )
                                    if match:
                                        file_path = match.group(1)
                                        content_parts.append(
                                            f"[Referenced file: {file_path}]"
                                        )
                                    else:
                                        content_parts.append("[Referenced file]")
                                except Exception:
                                    content_parts.append("[Referenced file]")
                            else:
                                content_parts.append(text)
                        elif item.get("type") == "tool_use":
                            tool_name = item.get("name", "unnamed_tool")
                            input_str = json.dumps(item.get("input", {}))
                            content_parts.append(
                                f"[Tool Use: {tool_name}]\n{input_str}"
                            )
                        elif item.get("type") == "tool_result":
                            content_parts.append(
                                f"[Tool Result]\n{item.get('content', '')}"
                            )
                content_str = "\n".join(content_parts)
            else:
                content_str = str(content)

            conversation_str += f"{role}: {content_str}\n\n"

        return conversation_str

    def _estimate_token_count(self, text: str) -> int:
        """Estimate token count as a fallback when API call fails.

        This is a very rough estimate and should only be used as a fallback.

        Args:
            text: Text to estimate token count for

        Returns:
            int: Estimated token count
        """
        # A rough estimate based on GPT tokenization (words / 0.75)
        words = len(text.split())
        return int(words / 0.75)

    def should_compact(self, agent_context, model: str, debug: bool = False) -> bool:
        """Check if a conversation should be compacted.

        Args:
            agent_context: AgentContext instance to get full API context from
            model: Model name to use for token counting
            debug: If True, print debug information about the compaction check

        Returns:
            bool: True if the conversation should be compacted
        """
        # Use accurate token counting method
        token_count = self.count_tokens(agent_context, model)

        # Get context window size for this model, default to 100k if not found
        context_window = self.model_context_windows.get(model, 100000)

        # Calculate threshold based on context window and threshold ratio
        token_threshold = int(context_window * self.threshold_ratio)

        should_compact = token_count > token_threshold

        # Print debug information if requested
        if debug:
            print("\n[Compaction Check]")
            print(f"  Model: {model}")
            print(f"  Context window: {context_window:,}")
            print(f"  Threshold ratio: {self.threshold_ratio:.0%}")
            print(f"  Token threshold: {token_threshold:,}")
            print(f"  Current tokens: {token_count:,}")
            print(f"  Usage: {token_count / context_window:.1%}")
            print(f"  Should compact: {should_compact}")

        return should_compact

    def generate_summary(self, agent_context, model: str) -> CompactionSummary:
        """Generate a summary of the conversation.

        Args:
            agent_context: AgentContext instance to get full API context from
            model: Model name to use for token counting

        Returns:
            CompactionSummary: Summary of the compacted conversation
        """
        # Get original token count using accurate method
        original_token_count = self.count_tokens(agent_context, model)

        # Get the API context to access processed messages
        context_dict = agent_context.get_api_context()
        messages_for_summary = context_dict["messages"]
        original_message_count = len(messages_for_summary)

        # Convert messages to a string for the summarization prompt
        # This will exclude file content blocks from the summary
        conversation_str = self._messages_to_string(
            messages_for_summary, for_summary=True
        )

        # Create summarization prompt
        system_prompt = """
        Summarize the following conversation for continuity.
        Include:
        1. Key points and decisions
        2. Current state of development/discussion
        3. Any outstanding questions or tasks
        4. The most recent context that future messages will reference
        
        Note: File references like [Referenced file: path] indicate files that were mentioned in the conversation.
        Acknowledge these references where relevant but don't spend time describing file contents.
        
        Be comprehensive yet concise. The summary will be used to start a new conversation 
        that continues where this one left off.
        """

        # Generate summary using Claude
        summary_messages = [{"role": "user", "content": conversation_str}]

        # Log the request if logger is available
        if self.logger:
            self.logger.log_request(
                messages=summary_messages,
                system_message=[{"type": "text", "text": system_prompt}],
                model=model,
                max_tokens=4000,
                tools=[],
                thinking_config=None,
            )

        response = self.client.messages.create(
            model=model,
            system=system_prompt,
            messages=summary_messages,
            max_tokens=4000,
        )

        # Log the response if logger is available
        if self.logger:
            self.logger.log_response(
                message=response,
                usage=response.usage,
                stop_reason=response.stop_reason,
                thinking_content=None,
            )

        summary = response.content[0].text
        # For summary token counting, estimate tokens since it's just the summary text
        summary_token_count = self._estimate_token_count(summary)
        compaction_ratio = float(summary_token_count) / float(original_token_count)

        return CompactionSummary(
            original_message_count=original_message_count,
            original_token_count=original_token_count,
            summary_token_count=summary_token_count,
            compaction_ratio=compaction_ratio,
            summary=summary,
        )

    def _archive_and_rotate(
        self,
        agent_context: AgentContext,
        new_messages: List[MessageParam],
        metadata: CompactionMetadata,
    ) -> str:
        """Archive the current conversation and update the context with new messages.

        Uses AgentContext.rotate() to maintain consistent file path conventions.
        This mutates the agent_context in place, including setting compaction metadata.

        Args:
            agent_context: AgentContext to archive and update (mutated in place)
            new_messages: New messages for the rotated context
            metadata: Compaction metadata to store in the context

        Returns:
            str: Archive filename
        """
        from datetime import datetime, timezone

        # Generate timestamp-based archive name
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_suffix = f"pre-compaction-{timestamp}"

        # Use AgentContext.rotate() to handle archiving, update context, and store metadata
        archive_name = agent_context.rotate(archive_suffix, new_messages, metadata)
        return archive_name

    def compact_conversation(
        self, agent_context, model: str, force: bool = False
    ) -> CompactionMetadata | None:
        """Compact a conversation by summarizing it, archiving the original, and updating the context.

        This method does ALL compaction work including:
        - Checking if compaction is needed
        - Generating the summary
        - Creating metadata
        - Archiving the original conversation
        - Updating the agent_context with compacted messages AND metadata (mutates in place)

        Args:
            agent_context: AgentContext instance (mutated in place if compaction occurs)
            model: Model name to use for token counting
            force: If True, force compaction even if under threshold

        Returns:
            CompactionMetadata if compaction occurred, None otherwise
        """
        if not force and not self.should_compact(agent_context, model):
            return None

        print("Initiating compaction...")
        # Generate summary
        summary = self.generate_summary(agent_context, model)

        # Create a new conversation with the summary as the first message
        new_messages = [
            {
                "role": "user",
                "content": (
                    f"### Conversation Summary (Compacted from {summary.original_message_count} previous messages)\n\n"
                    f"{summary.summary}\n\n"
                    f"Continue the conversation from this point."
                ),
            }
        ]

        # Optionally, retain the most recent few messages for immediate context
        # This is configurable - here we're adding the last user/assistant exchange
        context_dict = agent_context.get_api_context()
        messages_to_use = context_dict["messages"]
        preserve_message_count = 2
        if len(messages_to_use) >= preserve_message_count:
            if messages_to_use[-1]["role"] == "assistant":
                preserve_message_count = 1
            new_messages.extend(messages_to_use[-preserve_message_count:])

        # Strip all thinking blocks from compacted messages to avoid API validation errors
        # When thinking is enabled, the API requires the final assistant message to start
        # with a thinking block. Since we can't guarantee this structure after compaction
        # (we're preserving arbitrary messages), we strip all thinking blocks entirely.
        new_messages = self._strip_all_thinking_blocks(new_messages)

        # Create metadata for the compaction (archive_name will be set by rotate())
        metadata = CompactionMetadata(
            archive_name="",  # Will be updated by _archive_and_rotate
            original_message_count=summary.original_message_count,
            compacted_message_count=len(new_messages),
            original_token_count=summary.original_token_count,
            summary_token_count=summary.summary_token_count,
            compaction_ratio=summary.compaction_ratio,
        )

        # Archive the original conversation, update context in place, and store metadata
        archive_name = self._archive_and_rotate(agent_context, new_messages, metadata)

        # Update metadata with the actual archive name
        metadata.archive_name = archive_name

        return metadata

    def check_and_apply_compaction(
        self, agent_context, model: str, user_interface, enable_compaction: bool = True
    ) -> tuple:
        """Check if compaction is needed and apply it if necessary.

        Args:
            agent_context: The agent context to check (mutated in place if compaction occurs)
            model: Model name (string, not ModelSpec dict)
            user_interface: User interface for notifications
            enable_compaction: Whether compaction is enabled

        Returns:
            Tuple of (agent_context, True if compaction was applied)
        """
        import os

        # Check if debug mode is enabled
        debug_compaction = os.getenv("SILICA_DEBUG_COMPACTION", "").lower() in (
            "1",
            "true",
            "yes",
        )

        if not enable_compaction:
            if debug_compaction:
                print("[Compaction] Disabled via enable_compaction=False")
            return agent_context, False

        # Only check compaction when conversation state is complete
        # (no pending tool results and conversation has actual content)
        if agent_context.tool_result_buffer:
            if debug_compaction:
                print("[Compaction] Skipped: pending tool results")
            return agent_context, False

        if not agent_context.chat_history:
            if debug_compaction:
                print("[Compaction] Skipped: no chat history")
            return agent_context, False

        if len(agent_context.chat_history) <= 2:
            if debug_compaction:
                print(
                    f"[Compaction] Skipped: only {len(agent_context.chat_history)} messages"
                )
            return agent_context, False

        try:
            if debug_compaction:
                print("[Compaction] Checking if compaction needed...")
                # Call should_compact with debug flag to see detailed info
                should_compact = self.should_compact(agent_context, model, debug=True)
                if not should_compact:
                    print("[Compaction] Not needed yet")
                    return agent_context, False

            # Compact conversation - mutates agent_context in place if compaction occurs
            # This includes updating messages, clearing buffers, AND setting metadata
            metadata = self.compact_conversation(agent_context, model)

            if metadata:
                # Notify user about the compaction
                user_interface.handle_system_message(
                    f"[bold green]Conversation compacted: "
                    f"{metadata.original_message_count} messages → "
                    f"{metadata.compacted_message_count} messages "
                    f"(archived to {metadata.archive_name})[/bold green]",
                    markdown=False,
                )

                # Save the compacted session
                # Metadata was already set by rotate(), flush() will use it
                agent_context.flush(agent_context.chat_history, compact=False)
                return agent_context, True

        except Exception as e:
            # Log compaction errors but continue normally
            import traceback
            import sys

            error_details = traceback.format_exc()

            # Show user-friendly error message
            user_interface.handle_system_message(
                f"[yellow]Compaction check failed: {e}[/yellow]",
                markdown=False,
            )

            # Print detailed error to stderr for debugging
            print("\n[Compaction Error Details]", file=sys.stderr)
            print(error_details, file=sys.stderr)

        return agent_context, False
