#!/usr/bin/env python3
"""
Conversation compaction module for silica Developer.

This module provides functionality to compact long conversations by summarizing them
and starting a new conversation when they exceed certain token limits.
"""

import os
import json
from typing import List, Tuple
from dataclasses import dataclass
import anthropic
from anthropic.types import MessageParam
from dotenv import load_dotenv

from silica.developer.models import model_names, get_model

# Default threshold ratio of model's context window to trigger compaction
DEFAULT_COMPACTION_THRESHOLD_RATIO = 0.85  # Trigger compaction at 85% of context window


@dataclass
class CompactionSummary:
    """Summary of a compacted conversation."""

    original_message_count: int
    original_token_count: int
    summary_token_count: int
    compaction_ratio: float
    summary: str


@dataclass
class CompactionTransition:
    """Information about transitioning to a new session after compaction."""

    original_session_id: str
    new_session_id: str
    compacted_messages: List[MessageParam]
    summary: CompactionSummary


class ConversationCompacter:
    """Handles the compaction of long conversations into summaries."""

    def __init__(
        self, threshold_ratio: float = DEFAULT_COMPACTION_THRESHOLD_RATIO, client=None
    ):
        """Initialize the conversation compacter.

        Args:
            threshold_ratio: Ratio of model's context window to trigger compaction
            client: Anthropic client instance (optional, for testing)
        """
        self.threshold_ratio = threshold_ratio

        # Get model context window information

        self.model_context_windows = {
            model_data["title"]: model_data.get("context_window", 100000)
            for model_data in [get_model(ms) for ms in model_names()]
        }

        if client:
            self.client = client
        else:
            load_dotenv()
            self.api_key = os.getenv("ANTHROPIC_API_KEY")

            if not self.api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable not set")

            self.client = anthropic.Client(api_key=self.api_key)

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

            # Use the Anthropic API's count_tokens method with the actual parameters
            # that would be sent to the messages API
            response = self.client.messages.count_tokens(
                model=model,
                system=context_dict["system"],
                messages=context_dict["messages"],
                tools=context_dict["tools"] if context_dict["tools"] else None,
            )

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
        # Check the last message for tool_use without a following tool_result
        if not messages:
            return False

        last_message = messages[-1]
        if last_message.get("role") != "assistant":
            return False

        content = last_message.get("content", [])
        if not isinstance(content, list):
            return False

        # Check if last assistant message has tool_use
        has_tool_use = any(
            isinstance(block, dict) and block.get("type") == "tool_use"
            for block in content
        )

        # If we have tool_use in the last message, it's incomplete
        # (no chance for tool_result to follow)
        return has_tool_use

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

    def should_compact(self, agent_context, model: str) -> bool:
        """Check if a conversation should be compacted.

        Args:
            agent_context: AgentContext instance to get full API context from
            model: Model name to use for token counting

        Returns:
            bool: True if the conversation should be compacted
        """
        # Use accurate token counting method
        token_count = self.count_tokens(agent_context, model)

        # Get context window size for this model, default to 100k if not found
        context_window = self.model_context_windows.get(model, 100000)

        # Calculate threshold based on context window and threshold ratio
        token_threshold = int(context_window * self.threshold_ratio)

        return token_count > token_threshold

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
        response = self.client.messages.create(
            model=model,
            system=system_prompt,
            messages=[{"role": "user", "content": conversation_str}],
            max_tokens=4000,
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

    def compact_conversation(
        self, agent_context, model: str
    ) -> Tuple[List[MessageParam], CompactionSummary]:
        """Compact a conversation by summarizing it and creating a new conversation.

        Args:
            agent_context: AgentContext instance to get full API context from
            model: Model name to use for token counting

        Returns:
            Tuple containing:
                - List of MessageParam: New compacted conversation
                - CompactionSummary: Summary information about the compaction
        """
        if not self.should_compact(agent_context, model):
            return agent_context.chat_history, None

        # Generate summary
        summary = self.generate_summary(agent_context, model)

        # Create a new conversation with the summary as the system message
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
        if len(messages_to_use) >= 2:
            new_messages.extend(messages_to_use[-2:])

        return new_messages, summary

    def compact_and_transition(
        self, agent_context, model: str
    ) -> CompactionTransition | None:
        """Check if compaction is needed and prepare transition info.

        Args:
            agent_context: AgentContext instance to check and potentially compact
            model: Model name to use for token counting

        Returns:
            CompactionTransition if compaction occurred, None otherwise
        """
        if not self.should_compact(agent_context, model):
            return None

        # Generate compacted conversation
        compacted_messages, summary = self.compact_conversation(agent_context, model)

        if summary is None:
            return None

        # Create transition info
        from uuid import uuid4

        original_session_id = agent_context.session_id
        new_session_id = str(uuid4())

        return CompactionTransition(
            original_session_id=original_session_id,
            new_session_id=new_session_id,
            compacted_messages=compacted_messages,
            summary=summary,
        )
