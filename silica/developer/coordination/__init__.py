"""Coordination module for multi-agent orchestration via deaddrop."""

from .protocol import (
    MessageType,
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
    serialize_message,
    deserialize_message,
    COORDINATION_CONTENT_TYPE,
)
from .compression import compress_payload, decompress_payload
from .client import (
    CoordinationContext,
    ReceivedMessage,
    create_coordination_namespace,
    create_identity_with_invite,
    create_coordination_room,
)
from .worker_permissions import (
    create_worker_permission_callback,
    setup_worker_sandbox_permissions,
)

__all__ = [
    # Message types
    "MessageType",
    "TaskAssign",
    "TaskAck",
    "Progress",
    "Result",
    "PermissionRequest",
    "PermissionResponse",
    "Idle",
    "Question",
    "Answer",
    "Terminate",
    # Serialization
    "serialize_message",
    "deserialize_message",
    "COORDINATION_CONTENT_TYPE",
    # Compression
    "compress_payload",
    "decompress_payload",
    # Context
    "CoordinationContext",
    "ReceivedMessage",
    "create_coordination_namespace",
    "create_identity_with_invite",
    "create_coordination_room",
    # Worker permissions
    "create_worker_permission_callback",
    "setup_worker_sandbox_permissions",
]
