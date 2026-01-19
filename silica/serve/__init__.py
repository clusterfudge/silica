"""
Silica WebSocket server for remote agent sessions.

This module provides a bidirectional JSONL WebSocket interface that allows
any client to connect to and interact with silica agent sessions.
"""

from silica.serve.protocol import (
    # Protocol version
    PROTOCOL_VERSION,
    # Base types
    ClientMessage,
    ServerMessage,
    # Client -> Server messages
    UserInputMessage,
    ToolResponseMessage,
    InterruptMessage,
    PermissionResponseMessage,
    # Server -> Client messages
    AssistantMessageChunk,
    AssistantMessageComplete,
    SystemMessage,
    ToolUseMessage,
    ToolResultMessage,
    PermissionRequestMessage,
    TokenCountMessage,
    StatusMessage,
    ThinkingMessage,
    ErrorMessage,
    # Utilities
    parse_client_message,
    serialize_server_message,
)

__all__ = [
    "PROTOCOL_VERSION",
    "ClientMessage",
    "ServerMessage",
    "UserInputMessage",
    "ToolResponseMessage",
    "InterruptMessage",
    "PermissionResponseMessage",
    "AssistantMessageChunk",
    "AssistantMessageComplete",
    "SystemMessage",
    "ToolUseMessage",
    "ToolResultMessage",
    "PermissionRequestMessage",
    "TokenCountMessage",
    "StatusMessage",
    "ThinkingMessage",
    "ErrorMessage",
    "parse_client_message",
    "serialize_server_message",
]
