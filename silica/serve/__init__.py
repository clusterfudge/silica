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
    PingMessage,
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
    PongMessage,
    SessionInfoMessage,
    # Utilities
    parse_client_message,
    serialize_server_message,
    ProtocolError,
)
from silica.serve.ws_interface import WebSocketUserInterface

__all__ = [
    # Protocol
    "PROTOCOL_VERSION",
    "ClientMessage",
    "ServerMessage",
    "UserInputMessage",
    "ToolResponseMessage",
    "InterruptMessage",
    "PermissionResponseMessage",
    "PingMessage",
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
    "PongMessage",
    "SessionInfoMessage",
    "parse_client_message",
    "serialize_server_message",
    "ProtocolError",
    # Interface
    "WebSocketUserInterface",
]
