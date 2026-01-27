"""Agent Island IPC Client Library.

This library provides a Python client for communicating with the Agent Island
macOS application over a Unix domain socket using JSON-RPC 2.0.

Example usage:
    from agent_island import IslandClient

    async with IslandClient() as client:
        if client.connected:
            result = await client.permission_request(
                dialog_id="dlg-001",
                action="shell",
                resource="git push"
            )
"""

from .client import IslandClient
from .protocol import (
    PermissionDecision,
    AlertStyle,
    JsonRpcRequest,
    JsonRpcResponse,
    JsonRpcNotification,
)
from .exceptions import (
    IslandError,
    ConnectionError,
    ProtocolError,
    DialogNotFoundError,
    SessionNotFoundError,
)

__version__ = "1.0.0"
__all__ = [
    "IslandClient",
    "PermissionDecision",
    "AlertStyle",
    "JsonRpcRequest",
    "JsonRpcResponse",
    "JsonRpcNotification",
    "IslandError",
    "ConnectionError",
    "ProtocolError",
    "DialogNotFoundError",
    "SessionNotFoundError",
]
