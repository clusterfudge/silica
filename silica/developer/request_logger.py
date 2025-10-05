"""Request/Response logging for developer agent interactions.

This module provides functionality to log all API requests and responses
to a JSON log file for debugging and analysis purposes.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from anthropic.types import Message, MessageParam


class RequestResponseLogger:
    """Logger for API requests and responses."""

    def __init__(self, log_file_path: Optional[str] = None):
        """Initialize the logger.

        Args:
            log_file_path: Path to the log file. If None, logging is disabled.
        """
        self.log_file_path = Path(log_file_path) if log_file_path else None
        self.enabled = log_file_path is not None

        if self.enabled:
            # Create parent directory if it doesn't exist
            self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

            # Create or append to log file
            if not self.log_file_path.exists():
                self.log_file_path.write_text("")

    def log_request(
        self,
        messages: list[MessageParam],
        system_message: list[dict],
        model: str,
        max_tokens: int,
        tools: list[dict],
        thinking_config: Optional[dict] = None,
    ) -> None:
        """Log an API request.

        Args:
            messages: The conversation messages
            system_message: The system prompt
            model: The model name
            max_tokens: Maximum tokens for the response
            tools: The tools available to the model
            thinking_config: Optional thinking configuration
        """
        if not self.enabled:
            return

        log_entry = {
            "type": "request",
            "timestamp": datetime.now().isoformat(),
            "unix_timestamp": time.time(),
            "model": model,
            "max_tokens": max_tokens,
            "system": system_message,
            "messages": self._serialize_messages(messages),
            "tools": tools,
            "thinking": thinking_config,
        }

        self._write_log_entry(log_entry)

    def log_response(
        self,
        message: Message,
        usage: dict,
        stop_reason: str,
        thinking_content: Optional[str] = None,
    ) -> None:
        """Log an API response.

        Args:
            message: The response message from the API
            usage: Token usage information
            stop_reason: Why the response stopped
            thinking_content: Optional thinking content if present
        """
        if not self.enabled:
            return

        log_entry = {
            "type": "response",
            "timestamp": datetime.now().isoformat(),
            "unix_timestamp": time.time(),
            "message_id": message.id,
            "stop_reason": stop_reason,
            "content": self._serialize_content(message.content),
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_creation_input_tokens": getattr(
                    usage, "cache_creation_input_tokens", 0
                ),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
            },
            "thinking_content": thinking_content,
        }

        self._write_log_entry(log_entry)

    def log_tool_execution(
        self, tool_name: str, tool_input: dict, tool_result: dict
    ) -> None:
        """Log a tool execution.

        Args:
            tool_name: Name of the tool
            tool_input: Input parameters to the tool
            tool_result: Result from the tool execution
        """
        if not self.enabled:
            return

        log_entry = {
            "type": "tool_execution",
            "timestamp": datetime.now().isoformat(),
            "unix_timestamp": time.time(),
            "tool_name": tool_name,
            "input": tool_input,
            "result": self._serialize_tool_result(tool_result),
        }

        self._write_log_entry(log_entry)

    def log_error(self, error_type: str, error_message: str, context: dict) -> None:
        """Log an error.

        Args:
            error_type: Type of error
            error_message: Error message
            context: Additional context about the error
        """
        if not self.enabled:
            return

        log_entry = {
            "type": "error",
            "timestamp": datetime.now().isoformat(),
            "unix_timestamp": time.time(),
            "error_type": error_type,
            "error_message": error_message,
            "context": context,
        }

        self._write_log_entry(log_entry)

    def _serialize_messages(self, messages: list[MessageParam]) -> list[dict]:
        """Serialize messages to JSON-compatible format.

        Args:
            messages: List of message parameters

        Returns:
            Serialized messages
        """
        serialized = []
        for msg in messages:
            serialized_msg = {"role": msg["role"]}

            if isinstance(msg["content"], str):
                serialized_msg["content"] = msg["content"]
            elif isinstance(msg["content"], list):
                serialized_msg["content"] = []
                for block in msg["content"]:
                    if isinstance(block, dict):
                        serialized_msg["content"].append(block)
                    else:
                        # Handle non-dict content blocks
                        serialized_msg["content"].append(
                            self._serialize_content_block(block)
                        )

            serialized.append(serialized_msg)

        return serialized

    def _serialize_content(self, content: Any) -> list[dict]:
        """Serialize content blocks to JSON-compatible format.

        Args:
            content: Content blocks from the API response

        Returns:
            Serialized content
        """
        if isinstance(content, str):
            return [{"type": "text", "text": content}]

        serialized = []
        for block in content:
            serialized.append(self._serialize_content_block(block))

        return serialized

    def _serialize_content_block(self, block: Any) -> dict:
        """Serialize a single content block.

        Args:
            block: A content block

        Returns:
            Serialized block
        """
        if isinstance(block, dict):
            return block

        # Handle TextBlock
        if hasattr(block, "type") and block.type == "text":
            return {"type": "text", "text": block.text}

        # Handle ToolUseBlock
        if hasattr(block, "type") and block.type == "tool_use":
            return {
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            }

        # Handle ThinkingBlock
        if hasattr(block, "type") and block.type == "thinking":
            return {"type": "thinking", "thinking": getattr(block, "thinking", "")}

        # Fallback: try to convert to dict
        try:
            return vars(block)
        except (TypeError, AttributeError):
            return {"type": "unknown", "raw": str(block)}

    def _serialize_tool_result(self, result: dict) -> dict:
        """Serialize a tool result, truncating large content.

        Args:
            result: Tool result dictionary

        Returns:
            Serialized result with content potentially truncated
        """
        serialized = result.copy()

        # Truncate large content to avoid massive log files
        if "content" in serialized and isinstance(serialized["content"], str):
            max_content_length = 10000  # 10KB max per tool result
            if len(serialized["content"]) > max_content_length:
                serialized["content"] = (
                    serialized["content"][:max_content_length]
                    + f"\n\n[... truncated {len(serialized['content']) - max_content_length} characters ...]"
                )

        return serialized

    def _write_log_entry(self, entry: dict) -> None:
        """Write a log entry to the file.

        Args:
            entry: Log entry dictionary
        """
        try:
            with open(self.log_file_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            # Silently fail to avoid disrupting the main application
            # In a production system, we might want to log this somewhere
            pass
