"""
JSONL WebSocket Protocol for Silica.

This module defines the message types for bidirectional communication
between clients and the silica server over WebSocket.

Protocol Version: 1.0

Message Format:
- All messages are JSON objects terminated by newline (JSONL)
- Each message has a "type" field identifying its kind
- Messages are categorized as client->server or server->client
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

# Protocol version - increment when breaking changes are made
PROTOCOL_VERSION = "1.0"


# =============================================================================
# Enums
# =============================================================================


class MessageDirection(str, Enum):
    """Direction of message flow."""

    CLIENT_TO_SERVER = "client_to_server"
    SERVER_TO_CLIENT = "server_to_client"


class PermissionMode(str, Enum):
    """Permission grant modes."""

    ONCE = "once"
    ALWAYS_TOOL = "always_tool"
    ALWAYS_GROUP = "always_group"
    ALWAYS_COMMANDS = "always_commands"


# =============================================================================
# Client -> Server Messages
# =============================================================================


class UserInputMessage(BaseModel):
    """User text input to the agent."""

    type: Literal["user_input"] = "user_input"
    content: str = Field(..., description="The user's text input")
    session_id: Optional[str] = Field(
        None, description="Session ID to resume (optional)"
    )


class ToolResponseMessage(BaseModel):
    """Response to a tool use (for tools that delegate to client)."""

    type: Literal["tool_response"] = "tool_response"
    tool_use_id: str = Field(..., description="ID of the tool use being responded to")
    result: Dict[str, Any] = Field(..., description="Result of the tool execution")
    is_error: bool = Field(False, description="Whether the result is an error")


class InterruptMessage(BaseModel):
    """Interrupt the current agent operation."""

    type: Literal["interrupt"] = "interrupt"
    reason: Optional[str] = Field(None, description="Reason for interruption")


class PermissionResponseMessage(BaseModel):
    """Response to a permission request."""

    type: Literal["permission_response"] = "permission_response"
    request_id: str = Field(..., description="ID of the permission request")
    allowed: bool = Field(..., description="Whether permission is granted")
    mode: Optional[PermissionMode] = Field(
        None, description="Permission grant mode (if allowed)"
    )
    commands: Optional[List[str]] = Field(
        None, description="Specific commands to allow (for ALWAYS_COMMANDS mode)"
    )


class PingMessage(BaseModel):
    """Keepalive ping from client."""

    type: Literal["ping"] = "ping"
    timestamp: Optional[datetime] = None


# Union of all client message types
ClientMessage = Union[
    UserInputMessage,
    ToolResponseMessage,
    InterruptMessage,
    PermissionResponseMessage,
    PingMessage,
]


# =============================================================================
# Server -> Client Messages
# =============================================================================


class AssistantMessageChunk(BaseModel):
    """Streaming chunk of assistant response."""

    type: Literal["assistant_chunk"] = "assistant_chunk"
    content: str = Field(..., description="Text chunk from assistant")
    message_id: str = Field(..., description="ID of the message being streamed")


class AssistantMessageComplete(BaseModel):
    """Complete assistant message (sent after streaming finishes)."""

    type: Literal["assistant_complete"] = "assistant_complete"
    content: str = Field(..., description="Full message content")
    message_id: str = Field(..., description="ID of the completed message")


class SystemMessage(BaseModel):
    """System message (notifications, status updates)."""

    type: Literal["system_message"] = "system_message"
    content: str = Field(..., description="System message content")
    markdown: bool = Field(
        True, description="Whether content should be rendered as markdown"
    )
    level: Literal["info", "warning", "error"] = Field(
        "info", description="Message severity level"
    )


class ToolUseMessage(BaseModel):
    """Notification that the agent is using a tool."""

    type: Literal["tool_use"] = "tool_use"
    tool_use_id: str = Field(..., description="Unique ID for this tool use")
    tool_name: str = Field(..., description="Name of the tool being used")
    tool_params: Dict[str, Any] = Field(
        ..., description="Parameters passed to the tool"
    )


class ToolResultMessage(BaseModel):
    """Result of a tool execution."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str = Field(..., description="ID of the tool use this is a result for")
    tool_name: str = Field(..., description="Name of the tool")
    result: Dict[str, Any] = Field(..., description="Tool result data")
    is_error: bool = Field(False, description="Whether the result is an error")
    truncated: bool = Field(False, description="Whether the result was truncated")


class PermissionRequestMessage(BaseModel):
    """Request permission from client for an action."""

    type: Literal["permission_request"] = "permission_request"
    request_id: str = Field(..., description="Unique ID for this request")
    action: str = Field(
        ..., description="Action requiring permission (e.g., 'shell', 'read_file')"
    )
    resource: str = Field(
        ..., description="Resource being accessed (e.g., file path, command)"
    )
    group: Optional[str] = Field(
        None, description="Tool group for group-based permissions"
    )
    action_arguments: Optional[Dict[str, Any]] = Field(
        None, description="Additional arguments for display"
    )


class TokenCountMessage(BaseModel):
    """Token usage and cost information."""

    type: Literal["token_count"] = "token_count"
    prompt_tokens: int = Field(..., description="Tokens in the prompt")
    completion_tokens: int = Field(..., description="Tokens in the completion")
    total_tokens: int = Field(..., description="Total tokens used")
    total_cost: float = Field(..., description="Total cost in dollars")
    cached_tokens: Optional[int] = Field(None, description="Tokens read from cache")
    thinking_tokens: Optional[int] = Field(None, description="Thinking tokens used")
    thinking_cost: Optional[float] = Field(None, description="Cost of thinking tokens")
    elapsed_seconds: Optional[float] = Field(
        None, description="Wall-clock time elapsed"
    )


class StatusMessage(BaseModel):
    """Status update (e.g., processing, waiting)."""

    type: Literal["status"] = "status"
    message: str = Field(..., description="Status message")
    active: bool = Field(True, description="Whether status is ongoing")
    spinner: Optional[str] = Field(None, description="Spinner type for UI")


class ThinkingMessage(BaseModel):
    """Extended thinking content from the model."""

    type: Literal["thinking"] = "thinking"
    content: str = Field(..., description="Thinking content")
    tokens: int = Field(..., description="Number of thinking tokens")
    cost: float = Field(..., description="Cost of thinking tokens")
    collapsed: bool = Field(True, description="Whether to display collapsed")


class ErrorMessage(BaseModel):
    """Error message from server."""

    type: Literal["error"] = "error"
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(
        None, description="Additional error details"
    )
    recoverable: bool = Field(True, description="Whether client can recover")


class PongMessage(BaseModel):
    """Keepalive pong response."""

    type: Literal["pong"] = "pong"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SessionInfoMessage(BaseModel):
    """Session information sent on connection."""

    type: Literal["session_info"] = "session_info"
    session_id: str = Field(..., description="ID of the session")
    protocol_version: str = Field(
        default=PROTOCOL_VERSION, description="Protocol version"
    )
    resumed: bool = Field(False, description="Whether this is a resumed session")
    message_count: Optional[int] = Field(
        None, description="Number of messages in history"
    )


# Union of all server message types
ServerMessage = Union[
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
]


# =============================================================================
# Parsing and Serialization Utilities
# =============================================================================


# Map of message type strings to their Pydantic models
CLIENT_MESSAGE_TYPES: Dict[str, type] = {
    "user_input": UserInputMessage,
    "tool_response": ToolResponseMessage,
    "interrupt": InterruptMessage,
    "permission_response": PermissionResponseMessage,
    "ping": PingMessage,
}

SERVER_MESSAGE_TYPES: Dict[str, type] = {
    "assistant_chunk": AssistantMessageChunk,
    "assistant_complete": AssistantMessageComplete,
    "system_message": SystemMessage,
    "tool_use": ToolUseMessage,
    "tool_result": ToolResultMessage,
    "permission_request": PermissionRequestMessage,
    "token_count": TokenCountMessage,
    "status": StatusMessage,
    "thinking": ThinkingMessage,
    "error": ErrorMessage,
    "pong": PongMessage,
    "session_info": SessionInfoMessage,
}


class ProtocolError(Exception):
    """Error in protocol handling."""

    def __init__(
        self, code: str, message: str, details: Optional[Dict[str, Any]] = None
    ):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def parse_client_message(data: str | Dict[str, Any]) -> ClientMessage:
    """
    Parse a client message from JSON string or dict.

    Args:
        data: JSON string or already-parsed dict

    Returns:
        Parsed ClientMessage

    Raises:
        ProtocolError: If message is invalid or unknown type
    """
    import json

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            raise ProtocolError(
                code="INVALID_JSON",
                message=f"Failed to parse JSON: {e}",
                details={"raw_data": data[:100] if len(data) > 100 else data},
            )

    if not isinstance(data, dict):
        raise ProtocolError(
            code="INVALID_MESSAGE",
            message="Message must be a JSON object",
        )

    msg_type = data.get("type")
    if not msg_type:
        raise ProtocolError(
            code="MISSING_TYPE",
            message="Message must have a 'type' field",
        )

    model_class = CLIENT_MESSAGE_TYPES.get(msg_type)
    if not model_class:
        raise ProtocolError(
            code="UNKNOWN_TYPE",
            message=f"Unknown message type: {msg_type}",
            details={"valid_types": list(CLIENT_MESSAGE_TYPES.keys())},
        )

    try:
        return model_class(**data)
    except Exception as e:
        raise ProtocolError(
            code="VALIDATION_ERROR",
            message=f"Failed to validate message: {e}",
            details={"type": msg_type, "error": str(e)},
        )


def serialize_server_message(message: ServerMessage) -> str:
    """
    Serialize a server message to JSON string.

    Args:
        message: ServerMessage to serialize

    Returns:
        JSON string (without trailing newline - caller adds JSONL delimiter)
    """
    return message.model_dump_json()


def create_error_message(
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    recoverable: bool = True,
) -> ErrorMessage:
    """Helper to create an error message."""
    return ErrorMessage(
        code=code,
        message=message,
        details=details,
        recoverable=recoverable,
    )
