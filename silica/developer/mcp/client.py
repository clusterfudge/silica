"""MCP Client wrapper around the official MCP SDK.

Provides a simplified interface for connecting to MCP servers,
listing tools, and invoking tool calls.
"""

from dataclasses import dataclass, field
from typing import Any

from silica.developer.mcp.config import MCPServerConfig

__all__ = ["MCPClient", "MCPToolInfo"]


@dataclass
class MCPToolInfo:
    """Information about a tool exposed by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str  # Which server this tool belongs to


@dataclass
class MCPClient:
    """Client for connecting to a single MCP server.

    Wraps the MCP SDK's ClientSession and provides methods for
    tool discovery and invocation.
    """

    config: MCPServerConfig
    _connected: bool = field(default=False, init=False)
    _tools: list[MCPToolInfo] = field(default_factory=list, init=False)

    async def connect(self) -> None:
        """Connect to the MCP server and perform capability negotiation."""
        # Implementation will be added in task 716e5402
        raise NotImplementedError("MCPClient.connect() not yet implemented")

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        # Implementation will be added in task 716e5402
        raise NotImplementedError("MCPClient.disconnect() not yet implemented")

    async def list_tools(self, force_refresh: bool = False) -> list[MCPToolInfo]:
        """List tools available from this server.

        Args:
            force_refresh: If True, fetch fresh tool list even if cached.

        Returns:
            List of available tools.
        """
        # Implementation will be added in task 716e5402
        raise NotImplementedError("MCPClient.list_tools() not yet implemented")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool on this server.

        Args:
            tool_name: Name of the tool to call.
            arguments: Arguments to pass to the tool.

        Returns:
            Tool execution result.
        """
        # Implementation will be added in task 716e5402
        raise NotImplementedError("MCPClient.call_tool() not yet implemented")

    @property
    def is_connected(self) -> bool:
        """Whether the client is currently connected."""
        return self._connected

    @property
    def server_name(self) -> str:
        """Name of the server this client connects to."""
        return self.config.name
