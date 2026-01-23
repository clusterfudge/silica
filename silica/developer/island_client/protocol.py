"""JSON-RPC 2.0 protocol definitions for Agent Island."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import json


class AlertStyle(str, Enum):
    """Style for alert dialogs."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class PermissionDecision(str, Enum):
    """Possible responses to a permission request."""

    ALLOW = "allow"
    DENY = "deny"
    ALWAYS_TOOL = "always_tool"
    ALWAYS_GROUP = "always_group"
    ALWAYS_COMMANDS = "always_commands"
    DO_SOMETHING_ELSE = "do_something_else"


@dataclass
class JsonRpcRequest:
    """A JSON-RPC 2.0 request (expects a response)."""

    method: str
    params: Dict[str, Any]
    id: int
    jsonrpc: str = "2.0"

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(
            {
                "jsonrpc": self.jsonrpc,
                "method": self.method,
                "params": self.params,
                "id": self.id,
            }
        )

    def to_bytes(self) -> bytes:
        """Serialize to bytes with newline terminator."""
        return (self.to_json() + "\n").encode("utf-8")


@dataclass
class JsonRpcNotification:
    """A JSON-RPC 2.0 notification (no response expected)."""

    method: str
    params: Dict[str, Any]
    jsonrpc: str = "2.0"

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(
            {
                "jsonrpc": self.jsonrpc,
                "method": self.method,
                "params": self.params,
            }
        )

    def to_bytes(self) -> bytes:
        """Serialize to bytes with newline terminator."""
        return (self.to_json() + "\n").encode("utf-8")


@dataclass
class JsonRpcResponse:
    """A JSON-RPC 2.0 response."""

    id: int
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    jsonrpc: str = "2.0"

    @property
    def is_error(self) -> bool:
        """Check if this is an error response."""
        return self.error is not None

    @classmethod
    def from_json(cls, data: str) -> "JsonRpcResponse":
        """Parse from JSON string."""
        obj = json.loads(data)
        return cls(
            id=obj.get("id"),
            result=obj.get("result"),
            error=obj.get("error"),
            jsonrpc=obj.get("jsonrpc", "2.0"),
        )


@dataclass
class HandshakeParams:
    """Parameters for handshake request."""

    agent: str
    agent_version: str
    protocol_version: str = "1.0"
    capabilities: List[str] = field(
        default_factory=lambda: ["permissions", "ui", "thinking", "tools"]
    )
    pid: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "agent": self.agent,
            "agent_version": self.agent_version,
            "protocol_version": self.protocol_version,
            "capabilities": self.capabilities,
        }
        if self.pid is not None:
            result["pid"] = self.pid
        return result


@dataclass
class SessionRegisterParams:
    """Parameters for session.register request."""

    session_id: str
    agent_type: str
    working_directory: str
    model: Optional[str] = None
    persona: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "session_id": self.session_id,
            "agent_type": self.agent_type,
            "working_directory": self.working_directory,
        }
        if self.model:
            result["model"] = self.model
        if self.persona:
            result["persona"] = self.persona
        return result


@dataclass
class PermissionRequestParams:
    """Parameters for permission.request."""

    dialog_id: str
    action: str
    resource: str
    group: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    shell_parsed: Optional[Dict[str, Any]] = None
    hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "dialog_id": self.dialog_id,
            "action": self.action,
            "resource": self.resource,
        }
        if self.group:
            result["group"] = self.group
        if self.details:
            result["details"] = self.details
        if self.shell_parsed:
            result["shell_parsed"] = self.shell_parsed
        if self.hint:
            result["hint"] = self.hint
        return result


@dataclass
class PermissionResponse:
    """Parsed permission response."""

    decision: PermissionDecision
    commands: Optional[List[str]] = None  # For always_commands

    @classmethod
    def from_result(cls, result: Dict[str, Any]) -> "PermissionResponse":
        """Parse from JSON-RPC result."""
        decision_str = result.get("decision", "deny")
        decision = PermissionDecision(decision_str)
        commands = (
            result.get("commands")
            if decision == PermissionDecision.ALWAYS_COMMANDS
            else None
        )
        return cls(decision=decision, commands=commands)

    def to_silica_result(self) -> Union[bool, str, tuple]:
        """Convert to silica's PermissionResult type."""
        if self.decision == PermissionDecision.ALLOW:
            return True
        elif self.decision == PermissionDecision.DENY:
            return False
        elif self.decision == PermissionDecision.ALWAYS_TOOL:
            return "always_tool"
        elif self.decision == PermissionDecision.ALWAYS_GROUP:
            return "always_group"
        elif self.decision == PermissionDecision.ALWAYS_COMMANDS:
            return ("always_commands", set(self.commands or []))
        elif self.decision == PermissionDecision.DO_SOMETHING_ELSE:
            return "do_something_else"
        else:
            return False


@dataclass
class QuestionnaireQuestion:
    """A question in a questionnaire."""

    id: str
    prompt: str
    options: Optional[List[str]] = None
    default: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {"id": self.id, "prompt": self.prompt}
        if self.options:
            result["options"] = self.options
        if self.default:
            result["default"] = self.default
        return result


# Standard JSON-RPC error codes
class ErrorCode:
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Custom codes
    DIALOG_NOT_FOUND = -32000
    SESSION_NOT_FOUND = -32001
    PROTOCOL_MISMATCH = -32002
