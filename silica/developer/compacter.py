#!/usr/bin/env python3
"""
Conversation compaction module for silica Developer.

This module provides functionality to compact long conversations by summarizing them
and starting a new conversation when they exceed certain token limits.
"""

import copy
import os
import json
from typing import List
from dataclasses import dataclass
import anthropic
from anthropic.types import MessageParam

from silica.developer.context import AgentContext, _INTERNAL_MSG_KEYS
from silica.developer.models import model_names, get_model

# Default threshold ratio of model's context window to trigger compaction
DEFAULT_COMPACTION_THRESHOLD_RATIO = 0.80  # Trigger compaction at 80% of context window

# Default minimum token reduction ratio to achieve during compaction
DEFAULT_MIN_REDUCTION_RATIO = 0.30  # Compact enough to remove at least 30% of tokens


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
        min_reduction_ratio: float = DEFAULT_MIN_REDUCTION_RATIO,
        logger=None,
    ):
        """Initialize the conversation compacter.

        Args:
            client: Anthropic client instance (required)
            threshold_ratio: Ratio of model's context window to trigger compaction
            min_reduction_ratio: Minimum token reduction to achieve (default 30%)
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

        # Allow min reduction to be configured via environment variable
        env_min_reduction = os.getenv("SILICA_COMPACTION_MIN_REDUCTION")
        if env_min_reduction:
            try:
                min_reduction_ratio = float(env_min_reduction)
                if not 0.0 < min_reduction_ratio < 1.0:
                    print(
                        f"Warning: SILICA_COMPACTION_MIN_REDUCTION must be between 0 and 1, "
                        f"got {min_reduction_ratio}. Using default {DEFAULT_MIN_REDUCTION_RATIO}"
                    )
                    min_reduction_ratio = DEFAULT_MIN_REDUCTION_RATIO
            except ValueError:
                print(
                    f"Warning: Invalid SILICA_COMPACTION_MIN_REDUCTION value '{env_min_reduction}'. "
                    f"Using default {DEFAULT_MIN_REDUCTION_RATIO}"
                )
                min_reduction_ratio = DEFAULT_MIN_REDUCTION_RATIO

        self.threshold_ratio = threshold_ratio
        self.min_reduction_ratio = min_reduction_ratio
        self.logger = logger
        self.client = client

        # Get model context window information
        self.model_context_windows = {
            model_data["title"]: model_data.get("context_window", 100000)
            for model_data in [get_model(ms) for ms in model_names()]
        }

    def count_tokens(self, agent_context, model: str, messages: list = None) -> int:
        """Count tokens for the complete context sent to the API.

        This method accurately counts tokens for the complete API call including
        system prompt, tools, and messages - fixing HDEV-61.

        Args:
            agent_context: AgentContext instance to get full API context from
            model: Model name or alias to use for token counting
            messages: Optional override for messages (used when counting tokens
                for a subset of messages with the same system/tools context)

        Returns:
            int: Number of tokens for the complete context
        """
        # Resolve model alias to full model name for the API
        model_spec = get_model(model)
        model = model_spec["title"]

        try:
            # Get the full context from AgentContext
            context_dict = agent_context.get_api_context()

            # Allow overriding messages (useful for counting subsets)
            if messages is not None:
                context_dict = {
                    "system": context_dict["system"],
                    "tools": context_dict["tools"],
                    "messages": messages,
                }

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

    @staticmethod
    def _strip_internal_message_keys(
        messages: List[MessageParam],
    ) -> List[MessageParam]:
        """Strip internal metadata keys from messages before sending to the API.

        The agent loop annotates in-memory messages with keys like 'anthropic_id',
        'request_id', etc. for provenance tracking.  These are stripped when
        persisting to the context file, but the compacter works on the live
        in-memory chat_history which still carries them.  The Anthropic API
        rejects any extra top-level keys on messages, so we must strip them
        before making API calls.

        Additionally strips non-standard keys from content blocks (e.g.
        'citations', 'caller') that the SDK may add to responses but which
        are not accepted as input.

        Args:
            messages: Messages potentially containing internal keys

        Returns:
            Deep copy of messages with internal keys removed
        """
        # Known valid keys for content blocks by type
        _VALID_BLOCK_KEYS = {
            "text": {"type", "text", "cache_control"},
            "tool_use": {"type", "id", "name", "input", "cache_control"},
            "tool_result": {
                "type",
                "tool_use_id",
                "content",
                "is_error",
                "cache_control",
            },
            "image": {"type", "source", "cache_control"},
        }

        cleaned: list[MessageParam] = []
        for msg in messages:
            clean_msg = {k: v for k, v in msg.items() if k not in _INTERNAL_MSG_KEYS}
            # Also clean content blocks of non-standard keys
            content = clean_msg.get("content")
            if isinstance(content, list):
                clean_blocks = []
                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get("type", "")
                        valid_keys = _VALID_BLOCK_KEYS.get(block_type)
                        if valid_keys:
                            clean_blocks.append(
                                {
                                    k: copy.deepcopy(v)
                                    for k, v in block.items()
                                    if k in valid_keys
                                }
                            )
                        else:
                            # Unknown block type — deep copy as-is
                            clean_blocks.append(copy.deepcopy(block))
                    else:
                        clean_blocks.append(copy.deepcopy(block))
                clean_msg["content"] = clean_blocks
            elif isinstance(content, str):
                pass  # strings are fine as-is
            cleaned.append(clean_msg)
        return cleaned

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

    def _estimate_message_tokens(self, message: dict) -> int:
        """Estimate token count for a single message.

        Args:
            message: A single message dict with 'role' and 'content'

        Returns:
            int: Estimated token count for the message
        """
        total_chars = 0

        # Count role overhead (roughly 4 tokens for role markers)
        total_chars += 15

        content = message.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if "text" in item:
                        total_chars += len(item["text"])
                    elif item.get("type") == "tool_use":
                        total_chars += len(item.get("name", ""))
                        total_chars += len(json.dumps(item.get("input", {})))
                    elif item.get("type") == "tool_result":
                        result_content = item.get("content", "")
                        if isinstance(result_content, str):
                            total_chars += len(result_content)
                        elif isinstance(result_content, list):
                            for block in result_content:
                                if isinstance(block, dict) and "text" in block:
                                    total_chars += len(block["text"])

        # Rough estimate: 1 token per 3.5 characters
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
            model: Model name or alias to use for token counting
            debug: If True, print debug information about the compaction check

        Returns:
            bool: True if the conversation should be compacted
        """
        # Resolve model alias to full model name
        model_spec = get_model(model)
        model = model_spec["title"]

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

    def generate_summary_guidance(
        self, agent_context, model: str, messages_to_compact_count: int
    ) -> str:
        """Generate guidance for summarization using the current conversation context.

        This is Pass 1 of the two-pass compaction strategy. It asks the model
        (which has full context of the conversation) to identify what's important
        to preserve when summarizing the first N messages.

        This works because the current conversation fits in the context window
        (we're compacting because we're approaching the limit, not over it).
        The model can see both the messages we're about to compact AND the
        recent messages that depend on them.

        Args:
            agent_context: AgentContext instance with full conversation
            model: Model name or alias to use for guidance generation
            messages_to_compact_count: Number of messages that will be compacted

        Returns:
            A guidance string (~500-1000 tokens) identifying what to preserve
        """
        # Resolve model alias to full model name for the API
        model_spec = get_model(model)
        model_name = model_spec["title"]

        # Create a user message asking for guidance
        # This gets appended to the current conversation context
        guidance_request = f"""We are about to compact (summarize) the first {messages_to_compact_count} messages of this conversation to free up context space.

Please analyze the conversation and identify what MUST be preserved in the summary for the remaining conversation to make sense. Be concise but comprehensive.

Focus on:
1. **Key decisions made** - What was decided that affects later work?
2. **Important context** - What background info do the recent messages depend on?
3. **Current state** - What is the state of any ongoing work/tasks?
4. **Critical references** - What files, code, or concepts are referenced later?

Output a brief guidance document (under 500 words) that a summarizer can use to create an effective summary of those first {messages_to_compact_count} messages."""

        # Build the API call - this uses the existing conversation context
        # We're essentially asking the model "what should we preserve?"
        context_dict = agent_context.get_api_context()

        # Create messages: existing conversation + our guidance request
        messages_for_guidance = list(context_dict["messages"])
        messages_for_guidance.append({"role": "user", "content": guidance_request})

        # Log the request if logger is available
        # Include tools for cache efficiency (same prefix as original context)
        if self.logger:
            self.logger.log_request(
                messages=messages_for_guidance,
                system_message=context_dict["system"],
                model=model_name,
                max_tokens=2000,
                tools=context_dict["tools"] if context_dict["tools"] else [],
                thinking_config=None,
            )

        try:
            response = self.client.messages.create(
                model=model_name,
                tools=context_dict["tools"] if context_dict["tools"] else None,
                tool_choice={
                    "type": "none"
                },  # Prevent tool use, but keep tools for cache
                system=context_dict["system"],
                messages=messages_for_guidance,
                max_tokens=2000,
            )

            # Log the response if logger is available
            if self.logger:
                self.logger.log_response(
                    message=response,
                    usage=response.usage,
                    stop_reason=response.stop_reason,
                    thinking_content=None,
                )

            return self._extract_text_from_response(response)

        except Exception as e:
            # If guidance generation fails, return empty string
            # The caller can fall back to summarization without guidance
            print(f"[Compaction] Warning: Failed to generate summary guidance: {e}")
            return ""

    def generate_summary(
        self, agent_context, model: str, guidance: str = None
    ) -> CompactionSummary:
        """Generate a summary of the conversation.

        Args:
            agent_context: AgentContext instance to get full API context from
            model: Model name or alias to use for summarization
            guidance: Optional guidance from Pass 1 of two-pass compaction.
                      When provided, focuses the summary on what matters.

        Returns:
            CompactionSummary: Summary of the compacted conversation
        """
        # Resolve model alias to full model name for the API
        model_spec = get_model(model)
        model = model_spec["title"]

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

        # Check for active plan and include in summary context
        active_plan_context = ""
        try:
            from silica.developer.tools.planning import get_active_plan_status

            plan_status = get_active_plan_status(agent_context)
            if plan_status:
                status_emoji = "📋" if plan_status["status"] == "planning" else "🚀"
                active_plan_context = f"""

**IMPORTANT: Active Plan in Progress**
{status_emoji} Plan ID: {plan_status["id"]}
Title: {plan_status["title"]}
Status: {plan_status["status"]}
Tasks: {plan_status["total_tasks"] - plan_status["incomplete_tasks"]}/{plan_status["total_tasks"]} complete

The resumed conversation should continue working on this plan.
"""
        except Exception:
            pass  # Don't fail compaction if planning module has issues

        # Build guidance section if provided (from Pass 1 of two-pass compaction)
        guidance_section = ""
        if guidance:
            guidance_section = f"""
**IMPORTANT: Summary Guidance**
The following guidance was generated by analyzing the full conversation context.
Focus your summary on preserving this information:

{guidance}

---
"""

        # Create summarization prompt
        system_prompt = f"""
        Summarize the following conversation for continuity.
        {guidance_section}
        Include:
        1. Key points and decisions
        2. Current state of development/discussion
        3. Any outstanding questions or tasks
        4. The most recent context that future messages will reference
        
        Note: File references like [Referenced file: path] indicate files that were mentioned in the conversation.
        Acknowledge these references where relevant but don't spend time describing file contents.
        
        Be comprehensive yet concise. The summary will be used to start a new conversation 
        that continues where this one left off.
        {active_plan_context}"""

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

        summary = self._extract_text_from_response(response)

        if not summary:
            raise ValueError(
                f"No text content in response (stop_reason: {response.stop_reason})"
            )

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

    def _add_cache_control_to_last_block(self, message: dict) -> None:
        """Add cache_control to the last content block of a message.

        This marks the cache boundary so content before this point can be cached.
        Modifies the message in place.
        """
        content = message.get("content", "")

        if isinstance(content, str):
            # Convert to list format with cache_control
            message["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif isinstance(content, list) and content:
            # Add cache_control to the last block
            last_block = dict(content[-1])
            last_block["cache_control"] = {"type": "ephemeral"}
            content[-1] = last_block

    def _is_tool_result_only(self, content) -> bool:
        """Check if content consists only of tool_result blocks (no text).

        Args:
            content: Message content (string or list of blocks)

        Returns:
            bool: True if content has tool_result blocks but no text blocks
        """
        if not isinstance(content, list):
            return False

        has_text = any(isinstance(b, dict) and b.get("type") == "text" for b in content)
        has_tool_result = any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
        return has_tool_result and not has_text

    def _extract_text_from_response(self, response) -> str:
        """Extract and concatenate text from an API response.

        Args:
            response: Anthropic API response object

        Returns:
            str: Concatenated text from all text blocks in the response
        """
        if not response.content:
            return ""

        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "".join(text_parts)

    def _generate_summary_with_context(
        self,
        agent_context,
        messages_to_summarize: List[MessageParam],
        model: str,
        guidance: str,
    ) -> CompactionSummary:
        """Generate a summary using the same system/tools context for cache efficiency.

        This is Pass 2 of two-pass compaction. It reuses the same system prompt
        and tools from the original context (which are cached), but only includes
        the message prefix we want to summarize. Since messages_to_summarize is
        a prefix of the original messages, this also benefits from caching.

        Args:
            agent_context: Original AgentContext (for system prompt and tools)
            messages_to_summarize: Prefix of messages to summarize
            model: Model name or alias to use for summarization
            guidance: Guidance from Pass 1 about what to preserve

        Returns:
            CompactionSummary with the generated summary
        """
        if not messages_to_summarize:
            raise ValueError("No messages to summarize")

        # Resolve model alias to full model name for the API
        model_spec = get_model(model)
        model_name = model_spec["title"]

        original_message_count = len(messages_to_summarize)

        # Get the original context (system prompt and tools are cached)
        context_dict = agent_context.get_api_context()

        # Build the summarization request message
        summary_request = f"""Please summarize the conversation above for continuity. This summary will replace the messages you just saw.

**Summary Guidance (from analyzing the full conversation context):**
{guidance}

Focus on preserving what the guidance identifies as important. Be comprehensive yet concise."""

        # Strip internal metadata keys (e.g. anthropic_id) from messages
        # before sending to the API.  The in-memory chat_history carries these
        # for provenance tracking, but the API rejects unknown fields.
        clean_messages = self._strip_internal_message_keys(messages_to_summarize)

        # Prepare messages with summary request appended appropriately
        messages_for_summary = self._prepare_messages_for_summary(
            clean_messages, summary_request
        )

        # Estimate original token count
        original_token_count = self._estimate_token_count(
            self._messages_to_string(messages_to_summarize, for_summary=True)
        )

        # Log the request if logger is available
        if self.logger:
            self.logger.log_request(
                messages=messages_for_summary,
                system_message=context_dict["system"],
                model=model_name,
                max_tokens=4000,
                tools=context_dict["tools"] if context_dict["tools"] else [],
                thinking_config=None,
            )

        response = self.client.messages.create(
            model=model_name,
            system=context_dict["system"],
            tools=context_dict["tools"] if context_dict["tools"] else None,
            tool_choice={"type": "none"},  # Prevent tool use, but keep tools for cache
            messages=messages_for_summary,
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

        summary = self._extract_text_from_response(response)

        if not summary:
            raise ValueError(
                f"No text content in response (stop_reason: {response.stop_reason})"
            )

        summary_token_count = self._estimate_token_count(summary)
        compaction_ratio = (
            float(summary_token_count) / float(original_token_count)
            if original_token_count > 0
            else 0
        )

        return CompactionSummary(
            original_message_count=original_message_count,
            original_token_count=original_token_count,
            summary_token_count=summary_token_count,
            compaction_ratio=compaction_ratio,
            summary=summary,
        )

    def _prepare_messages_for_summary(
        self, messages_to_summarize: List[MessageParam], summary_request: str
    ) -> List[MessageParam]:
        """Prepare messages for summary generation by appending the summary request.

        Uses guard clauses to handle different message ending scenarios:
        - Ends with assistant: append new user message
        - Ends with tool_result-only user message: add assistant acknowledgment + user request
        - Ends with user message (string content): convert to list and append request
        - Ends with user message (list content): add cache control and append request

        Args:
            messages_to_summarize: Original messages to summarize
            summary_request: The summary request text to append

        Returns:
            List of messages ready for the summarization API call
        """
        messages_for_summary = list(messages_to_summarize)
        last_msg = messages_for_summary[-1]

        # Guard: ends with assistant - just append new user message
        if last_msg.get("role") != "user":
            self._add_cache_control_to_last_block(messages_for_summary[-1])
            messages_for_summary.append({"role": "user", "content": summary_request})
            return messages_for_summary

        existing_content = last_msg.get("content", "")

        # Guard: tool_result-only message needs assistant acknowledgment first
        if self._is_tool_result_only(existing_content):
            self._add_cache_control_to_last_block(messages_for_summary[-1])
            messages_for_summary.append(
                {
                    "role": "assistant",
                    "content": "I'll analyze the conversation for summarization.",
                }
            )
            messages_for_summary.append({"role": "user", "content": summary_request})
            return messages_for_summary

        # Guard: string content - convert to list format
        if isinstance(existing_content, str):
            new_content = [
                {
                    "type": "text",
                    "text": existing_content,
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": "\n\n---\n\n" + summary_request},
            ]
            messages_for_summary[-1] = {"role": "user", "content": new_content}
            return messages_for_summary

        # Guard: list content - add cache control and append request
        if isinstance(existing_content, list):
            new_content = list(existing_content)
            if new_content:
                last_block = dict(new_content[-1])
                last_block["cache_control"] = {"type": "ephemeral"}
                new_content[-1] = last_block
            new_content.append(
                {"type": "text", "text": "\n\n---\n\n" + summary_request}
            )
            messages_for_summary[-1] = {"role": "user", "content": new_content}
            return messages_for_summary

        # Fallback: unknown content type - just set the summary request
        messages_for_summary[-1] = {
            "role": "user",
            "content": [{"type": "text", "text": summary_request}],
        }
        return messages_for_summary

    def _archive_and_rotate(
        self,
        agent_context: AgentContext,
        new_messages: List[MessageParam],
        metadata: CompactionMetadata,
    ) -> str:
        """Archive the current conversation and update the context with new messages.

        For root contexts, archives the conversation to a timestamped file and rotates.
        For sub-agent contexts, compacts in place without archiving (sub-agents are
        ephemeral and don't need conversation archives).

        This mutates the agent_context in place, including setting compaction metadata.

        Args:
            agent_context: AgentContext to archive and update (mutated in place)
            new_messages: New messages for the rotated context
            metadata: Compaction metadata to store in the context

        Returns:
            str: Archive filename (or "compact-in-place" for sub-agents)
        """
        # Sub-agent contexts can't rotate (no root.json to archive).
        # Compact in place instead — the summary is what matters, not the archive.
        if agent_context.parent_session_id is not None:
            agent_context.compact_in_place(new_messages, metadata)
            return "compact-in-place"

        from datetime import datetime, timezone

        # Generate timestamp-based archive name
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_suffix = f"pre-compaction-{timestamp}"

        # Use AgentContext.rotate() to handle archiving, update context, and store metadata
        archive_name = agent_context.rotate(archive_suffix, new_messages, metadata)
        return archive_name

    def calculate_turns_for_target_reduction(
        self,
        agent_context,
        model: str,
        target_reduction_ratio: float = None,
        debug: bool = False,
    ) -> int:
        """Calculate the number of turns to compact to achieve target token reduction.

        This method estimates tokens per turn and finds the minimum number of turns
        to compact that will achieve at least the target reduction ratio.

        The goal is to compact enough content to "buy" several turns of headroom,
        rather than compacting just a tiny bit and needing to compact again soon.

        Args:
            agent_context: AgentContext instance to analyze
            model: Model name for token counting
            target_reduction_ratio: Minimum reduction to achieve (default: self.min_reduction_ratio)
            debug: If True, print debug information

        Returns:
            int: Number of turns to compact (minimum 1)
        """
        if target_reduction_ratio is None:
            target_reduction_ratio = self.min_reduction_ratio

        messages = agent_context.chat_history
        if len(messages) < 3:
            return 1  # Can't really compact less than 1 turn

        # Get total token count for context
        total_tokens = self.count_tokens(agent_context, model)

        # Estimate the "base" tokens (system prompt + tools) that won't be reduced
        # These stay constant regardless of how many messages we compact
        context_dict = agent_context.get_api_context()
        base_tokens = 0
        if context_dict.get("system"):
            for block in context_dict["system"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    base_tokens += int(len(block.get("text", "")) / 3.5)
        if context_dict.get("tools"):
            base_tokens += int(len(json.dumps(context_dict["tools"])) / 3.5)

        # Estimate message tokens (total - base)
        message_tokens = total_tokens - base_tokens

        # Calculate tokens to remove for target reduction
        # We want: (total - removed_tokens) / total <= (1 - target_reduction_ratio)
        # So: removed_tokens >= total * target_reduction_ratio
        tokens_to_remove = int(total_tokens * target_reduction_ratio)

        if debug:
            print("\n[Smart Compaction Calculation]")
            print(f"  Total tokens: {total_tokens:,}")
            print(f"  Base tokens (system+tools): {base_tokens:,}")
            print(f"  Message tokens: {message_tokens:,}")
            print(f"  Target reduction: {target_reduction_ratio:.0%}")
            print(f"  Tokens to remove: {tokens_to_remove:,}")

        # Estimate tokens per message by sampling
        # A "turn" is user+assistant, so we estimate pairs
        cumulative_tokens = 0
        turns_needed = 0
        messages_counted = 0

        # Iterate through messages, accumulating token estimates
        # until we reach our target
        for i, message in enumerate(messages):
            msg_tokens = self._estimate_message_tokens(message)
            cumulative_tokens += msg_tokens
            messages_counted += 1

            # Check if this completes a turn (user+assistant pair)
            # We need to keep at least 1 message (the current user query context)
            if i > 0 and messages_counted >= 2:
                # Calculate turns: ceil(messages / 2) roughly
                # Turn 1 = 1 msg (user), Turn 2 = 3 msgs (u,a,u), etc.
                # So messages_counted maps to turns as: (messages_counted + 1) / 2
                potential_turns = (messages_counted + 1) // 2

                if debug and i < 10:  # Only print first few for brevity
                    print(
                        f"  Message {i}: +{msg_tokens:,} tokens, "
                        f"cumulative: {cumulative_tokens:,}, turns: {potential_turns}"
                    )

                # Check if we've accumulated enough tokens
                if cumulative_tokens >= tokens_to_remove:
                    turns_needed = potential_turns
                    break

        # If we went through all messages without hitting target,
        # compact as much as possible (leave 1 message)
        if turns_needed == 0:
            # Calculate max turns we can compact (leave at least 1 message)
            max_messages_to_compact = len(messages) - 1
            turns_needed = max((max_messages_to_compact + 1) // 2, 1)

        # Ensure minimum of 1 turn
        turns_needed = max(turns_needed, 1)

        # Cap at a reasonable maximum (don't compact everything)
        # Leave at least 2 messages (1 turn of context)
        max_turns = max((len(messages) - 2 + 1) // 2, 1)
        turns_needed = min(turns_needed, max_turns)

        if debug:
            print(f"  Final turns to compact: {turns_needed}")
            expected_reduction = cumulative_tokens / total_tokens if total_tokens else 0
            print(f"  Expected reduction: {expected_reduction:.0%}")

        return turns_needed

    def compact_conversation(
        self, agent_context, model: str, turns: int = None, force: bool = False
    ) -> CompactionMetadata | None:
        """Compact a conversation by summarizing first N turns and keeping the rest.

        This is a micro-compaction approach that:
        - Summarizes only the first N conversation turns
        - If turns is None, automatically calculates turns to achieve 30% reduction
        - Keeps all remaining messages unchanged
        - Uses haiku model for cost-effectiveness
        - Better preserves recent context than full compaction

        Args:
            agent_context: AgentContext instance (mutated in place if compaction occurs)
            model: Model name to use for summarization (typically "haiku")
            turns: Number of turns to compact (if None, auto-calculate for 30% reduction)
            force: If True, force compaction even if under threshold

        Returns:
            CompactionMetadata if compaction occurred, None otherwise
        """
        # Check if compaction should proceed
        if not force and not self.should_compact(agent_context, model):
            return None

        # Check if debug mode is enabled
        debug_compaction = os.getenv("SILICA_DEBUG_COMPACTION", "").lower() in (
            "1",
            "true",
            "yes",
        )

        # Auto-calculate turns if not specified
        if turns is None:
            turns = self.calculate_turns_for_target_reduction(
                agent_context, model, debug=debug_compaction
            )

        # Calculate number of messages for N turns
        # Turn structure: must start with user and end with user
        # Turn 1: 1 message (user)
        # Turn 2: 3 messages (user, assistant, user)
        # Turn 3: 5 messages (user, assistant, user, assistant, user)
        # Turn N: (2N - 1) messages
        messages_to_compact = (turns * 2) - 1

        # Check if there's enough conversation to compact with the requested turns
        # If not enough messages, adjust turns to compact all but the last message
        if len(agent_context.chat_history) <= messages_to_compact:
            if len(agent_context.chat_history) <= 2:
                # Not enough to compact at all
                return None
            # Adjust to compact all messages except the last one
            messages_to_compact = len(agent_context.chat_history) - 1
            adjusted_turns = (messages_to_compact + 1) // 2
            turns = adjusted_turns

        # Show progress: starting compaction
        print("Compacting conversation...")

        # Separate messages to compact from messages to keep
        messages_to_summarize = agent_context.chat_history[:messages_to_compact]
        messages_to_keep = agent_context.chat_history[messages_to_compact:]

        # Two-pass compaction leverages caching for efficiency:
        #
        # Pass 1: Full context (cached) + "what should we preserve?"
        #   - Reuses cached system prompt, tools, and all messages
        #   - Model sees full context so it knows what later messages depend on
        #
        # Pass 2: Same system/tools (cached) + messages prefix (cached) + guidance
        #   - System prompt and tools are identical → cached
        #   - Messages 1-N are a PREFIX of the original → cached
        #   - Only the guidance/summary request is new

        # Show progress: Pass 1
        print("Pass 1/2: Analyzing context for key information...")

        if debug_compaction:
            print(
                "[Compaction] Pass 1: Generating summary guidance from full context..."
            )

        guidance = self.generate_summary_guidance(
            agent_context, model, messages_to_compact
        )

        if debug_compaction:
            print(f"[Compaction] Pass 1 complete. Guidance: {len(guidance)} chars")

        # Show progress: Pass 2
        print("Pass 2/2: Generating summary...")

        # Pass 2: Use same system/tools + message prefix + guidance
        summary_obj = self._generate_summary_with_context(
            agent_context, messages_to_summarize, model, guidance
        )
        summary = summary_obj.summary

        # Create new message history with summary + kept messages
        new_messages = [
            {
                "role": "user",
                "content": f"### Compacted Summary (first {turns} turns)\n\n{summary}\n\n---\n\nContinuing with remaining conversation...",
            }
        ]
        new_messages.extend(messages_to_keep)

        # Strip all thinking blocks from compacted messages
        new_messages = self._strip_all_thinking_blocks(new_messages)

        # Remove orphaned tool blocks (tool_use without tool_result OR tool_result without tool_use)
        # This can happen when compaction splits a tool use/result pair
        from silica.developer.compaction_validation import strip_orphaned_tool_blocks

        new_messages = strip_orphaned_tool_blocks(new_messages)

        # Disable thinking mode after stripping thinking blocks
        if agent_context.thinking_mode != "off":
            agent_context.thinking_mode = "off"

        # Create metadata for the compaction
        metadata = CompactionMetadata(
            archive_name="",  # Will be updated by _archive_and_rotate
            original_message_count=len(agent_context.chat_history),
            compacted_message_count=len(new_messages),
            original_token_count=summary_obj.original_token_count,
            summary_token_count=summary_obj.summary_token_count,
            compaction_ratio=summary_obj.compaction_ratio,
        )

        # Archive the original conversation, update context in place, and store metadata
        archive_name = self._archive_and_rotate(agent_context, new_messages, metadata)

        # Update metadata with the actual archive name
        metadata.archive_name = archive_name

        return metadata

    def _make_json_serializable(self, obj):
        """Recursively convert objects to JSON-serializable types.

        Handles Anthropic SDK objects like ThinkingBlock, TextBlock, etc.
        """
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._make_json_serializable(v) for v in obj]
        # Handle Anthropic SDK objects - convert to dict
        if hasattr(obj, "__dict__"):
            # Get the type name for debugging
            type_name = type(obj).__name__
            result = {"_type": type_name}
            for key, value in obj.__dict__.items():
                if not key.startswith("_"):
                    result[key] = self._make_json_serializable(value)
            return result
        # Fallback to string representation
        return str(obj)

    def _dump_compaction_debug(
        self, agent_context, model: str, error: Exception
    ) -> None:
        """Dump compaction debug info to disk for analysis.

        When compaction fails, this dumps all the relevant data to a debug file
        so we can analyze what went wrong.

        Args:
            agent_context: The agent context that failed to compact
            model: Model name that was being used
            error: The exception that occurred
        """
        from datetime import datetime
        from pathlib import Path
        import traceback

        try:
            # Create debug directory
            debug_dir = Path.home() / ".silica" / "compaction_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_file = debug_dir / f"compaction_failed_{timestamp}.json"

            # Get the API context that would be sent
            context_dict = agent_context.get_api_context()

            # Make everything JSON serializable
            context_dict = self._make_json_serializable(context_dict)

            # Calculate sizes of each component
            system_size = 0
            if context_dict.get("system"):
                system_json = json.dumps(context_dict["system"])
                system_size = len(system_json)

            tools_size = 0
            if context_dict.get("tools"):
                tools_json = json.dumps(context_dict["tools"])
                tools_size = len(tools_json)

            messages_size = 0
            if context_dict.get("messages"):
                messages_json = json.dumps(context_dict["messages"])
                messages_size = len(messages_json)

            # Build the conversation string that would be sent to generate_summary
            messages_for_summary = context_dict.get("messages", [])
            conversation_str = self._messages_to_string(
                messages_for_summary, for_summary=True
            )
            conversation_str_size = len(conversation_str)

            # Build debug payload
            debug_payload = {
                "timestamp": timestamp,
                "error": str(error),
                "error_traceback": traceback.format_exc(),
                "model": model,
                "sizes": {
                    "system_chars": system_size,
                    "tools_chars": tools_size,
                    "messages_chars": messages_size,
                    "conversation_str_chars": conversation_str_size,
                    "total_chars": system_size + tools_size + messages_size,
                    "estimated_tokens": {
                        "system": int(system_size / 3.5),
                        "tools": int(tools_size / 3.5),
                        "messages": int(messages_size / 3.5),
                        "conversation_str": int(conversation_str_size / 3.5),
                        "total": int((system_size + tools_size + messages_size) / 3.5),
                    },
                },
                "message_count": len(messages_for_summary),
                "message_details": [],
                # The actual payloads (can be large)
                "system": context_dict.get("system"),
                "tools": context_dict.get("tools"),
                "messages": context_dict.get("messages"),
                "conversation_str_for_summary": conversation_str,
            }

            # Add per-message size details
            for i, msg in enumerate(messages_for_summary):
                msg_json = json.dumps(msg)
                msg_size = len(msg_json)
                debug_payload["message_details"].append(
                    {
                        "index": i,
                        "role": msg.get("role", "unknown"),
                        "chars": msg_size,
                        "estimated_tokens": int(msg_size / 3.5),
                        "content_preview": str(msg.get("content", ""))[:200] + "..."
                        if len(str(msg.get("content", ""))) > 200
                        else str(msg.get("content", "")),
                    }
                )

            # Write to file
            with open(debug_file, "w") as f:
                json.dump(debug_payload, f, indent=2, default=str)

            print(f"\n[Compaction Debug] Dumped debug info to: {debug_file}")
            print(
                f"  System: {system_size:,} chars (~{int(system_size / 3.5):,} tokens)"
            )
            print(f"  Tools: {tools_size:,} chars (~{int(tools_size / 3.5):,} tokens)")
            print(
                f"  Messages: {messages_size:,} chars (~{int(messages_size / 3.5):,} tokens)"
            )
            print(
                f"  Conversation str: {conversation_str_size:,} chars (~{int(conversation_str_size / 3.5):,} tokens)"
            )
            print(f"  Message count: {len(messages_for_summary)}")

        except Exception as dump_error:
            print(f"\n[Compaction Debug] Failed to dump debug info: {dump_error}")

    def check_and_apply_compaction(
        self, agent_context, model: str, user_interface, enable_compaction: bool = True
    ) -> tuple:
        """Check if compaction is needed and apply it if necessary.

        Uses smart compaction to automatically determine how many turns to compact
        based on achieving at least 30% token reduction. This ensures that when we
        compact, we remove enough content to provide headroom for several more turns
        before needing to compact again.

        Args:
            agent_context: The agent context to check (mutated in place if compaction occurs)
            model: Model name (string, not ModelSpec dict) - used for token counting only
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

            # Use smart compaction: auto-calculate turns for 30% reduction
            # Uses haiku model for cost-effectiveness
            metadata = self.compact_conversation(
                agent_context, "haiku", turns=None, force=False
            )

            if metadata:
                # Calculate actual reduction for user feedback
                if metadata.original_message_count > 0:
                    msg_reduction_pct = (
                        1
                        - metadata.compacted_message_count
                        / metadata.original_message_count
                    ) * 100
                else:
                    msg_reduction_pct = 0

                # Format token counts compactly (e.g., "225K" or "8K")
                def format_tokens(tokens: int) -> str:
                    if tokens >= 1000:
                        return f"{tokens / 1000:.0f}K"
                    return str(tokens)

                orig_tokens = format_tokens(metadata.original_token_count)
                summary_tokens = format_tokens(metadata.summary_token_count)

                # Notify user about the compaction with compact summary
                user_interface.handle_system_message(
                    f"[bold green]✓ Compacted: "
                    f"{metadata.original_message_count} msgs → {metadata.compacted_message_count} msgs "
                    f"({msg_reduction_pct:.0f}% reduction) | "
                    f"{orig_tokens} → {summary_tokens} tokens | "
                    f"archived to {metadata.archive_name}[/bold green]",
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

            # Dump debug info to disk for analysis
            self._dump_compaction_debug(agent_context, model, e)

        return agent_context, False
