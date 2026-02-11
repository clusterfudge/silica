"""Message protocol for coordinator-agent communication.

Defines dataclasses for all message types exchanged between coordinators,
workers, and humans via deaddrop.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Union
import json


class MessageType(str, Enum):
    """Types of messages in the coordination protocol."""

    # Coordinator -> Agent
    TASK_ASSIGN = "task_assign"
    PERMISSION_RESPONSE = "permission_response"
    ANSWER = "answer"
    TERMINATE = "terminate"

    # Agent -> Coordinator
    TASK_ACK = "task_ack"
    PROGRESS = "progress"
    RESULT = "result"
    PERMISSION_REQUEST = "permission_request"
    QUESTION = "question"
    IDLE = "idle"


# Content type for coordination messages
COORDINATION_CONTENT_TYPE = "application/vnd.silica.coordination+json"


@dataclass
class TaskAssign:
    """Task assignment from coordinator to agent."""

    type: str = field(default=MessageType.TASK_ASSIGN.value, init=False)
    task_id: str = ""
    description: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    deadline: Optional[str] = None  # ISO 8601 format

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskAssign":
        data.pop("type", None)
        return cls(**data)


@dataclass
class TaskAck:
    """Task acknowledgment from agent to coordinator."""

    type: str = field(default=MessageType.TASK_ACK.value, init=False)
    task_id: str = ""
    agent_id: str = ""
    acknowledged_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskAck":
        data.pop("type", None)
        return cls(**data)


@dataclass
class Progress:
    """Progress update from agent (typically broadcast to room)."""

    type: str = field(default=MessageType.PROGRESS.value, init=False)
    task_id: str = ""
    agent_id: str = ""
    progress: Optional[float] = None  # 0.0 to 1.0
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Progress":
        data.pop("type", None)
        return cls(**data)


@dataclass
class Result:
    """Task result from agent to coordinator."""

    type: str = field(default=MessageType.RESULT.value, init=False)
    task_id: str = ""
    agent_id: str = ""
    status: str = "complete"  # "complete", "failed", "blocked", "partial"
    data: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Result":
        data.pop("type", None)
        return cls(**data)


@dataclass
class PermissionRequest:
    """Permission request from agent to coordinator."""

    type: str = field(default=MessageType.PERMISSION_REQUEST.value, init=False)
    request_id: str = ""
    task_id: str = ""
    agent_id: str = ""
    action: str = ""  # e.g., "shell_execute", "write_file"
    resource: str = ""  # e.g., command string, file path
    context: str = ""  # Human-readable explanation
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PermissionRequest":
        data.pop("type", None)
        return cls(**data)


@dataclass
class PermissionResponse:
    """Permission response from coordinator to agent."""

    type: str = field(default=MessageType.PERMISSION_RESPONSE.value, init=False)
    request_id: str = ""
    decision: str = ""  # "allow", "deny", "timeout"
    reason: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PermissionResponse":
        data.pop("type", None)
        return cls(**data)


@dataclass
class Idle:
    """Idle notification from agent (broadcast to room)."""

    type: str = field(default=MessageType.IDLE.value, init=False)
    agent_id: str = ""
    completed_task_id: Optional[str] = None
    available_since: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Idle":
        data.pop("type", None)
        return cls(**data)


@dataclass
class Question:
    """Question from agent to coordinator."""

    type: str = field(default=MessageType.QUESTION.value, init=False)
    question_id: str = ""
    task_id: str = ""
    agent_id: str = ""
    question: str = ""
    options: list[str] = field(default_factory=list)  # Optional predefined options
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Question":
        data.pop("type", None)
        return cls(**data)


@dataclass
class Answer:
    """Answer from coordinator to agent."""

    type: str = field(default=MessageType.ANSWER.value, init=False)
    question_id: str = ""
    task_id: str = ""
    answer: str = ""
    context: Optional[str] = None  # Additional context
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Answer":
        data.pop("type", None)
        return cls(**data)


@dataclass
class Terminate:
    """Termination request from coordinator to agent."""

    type: str = field(default=MessageType.TERMINATE.value, init=False)
    reason: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Terminate":
        data.pop("type", None)
        return cls(**data)


# Type alias for all message types
CoordinationMessage = Union[
    TaskAssign,
    TaskAck,
    Progress,
    Result,
    PermissionRequest,
    PermissionResponse,
    Idle,
    Question,
    Answer,
    Terminate,
]

# Registry for deserializing messages by type
MESSAGE_CLASSES: dict[str, type] = {
    MessageType.TASK_ASSIGN.value: TaskAssign,
    MessageType.TASK_ACK.value: TaskAck,
    MessageType.PROGRESS.value: Progress,
    MessageType.RESULT.value: Result,
    MessageType.PERMISSION_REQUEST.value: PermissionRequest,
    MessageType.PERMISSION_RESPONSE.value: PermissionResponse,
    MessageType.IDLE.value: Idle,
    MessageType.QUESTION.value: Question,
    MessageType.ANSWER.value: Answer,
    MessageType.TERMINATE.value: Terminate,
}


def serialize_message(message: CoordinationMessage) -> str:
    """Serialize a coordination message to JSON string."""
    return json.dumps(message.to_dict())


def deserialize_message(data: str | dict[str, Any]) -> CoordinationMessage:
    """Deserialize a coordination message from JSON string or dict.

    Args:
        data: JSON string or dict containing message data

    Returns:
        Appropriate message dataclass instance

    Raises:
        ValueError: If message type is unknown or data is invalid
    """
    if isinstance(data, str):
        data = json.loads(data)

    msg_type = data.get("type")
    if not msg_type:
        raise ValueError("Message missing 'type' field")

    msg_class = MESSAGE_CLASSES.get(msg_type)
    if not msg_class:
        raise ValueError(f"Unknown message type: {msg_type}")

    return msg_class.from_dict(data)
