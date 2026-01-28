"""MCP Tool Manager for orchestrating multiple MCP server connections.

Manages the lifecycle of multiple MCP clients and provides a unified
interface for tool discovery and invocation across all connected servers.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from silica.developer.mcp.client import (
    MCPClient,
    MCPConnectionError,
    MCPServerCrashedError,
    MCPTimeoutError,
    MCPToolError,
    MCPToolInfo,
)
from silica.developer.mcp.config import MCPConfig, MCPServerConfig

__all__ = ["MCPToolManager", "ServerStatus"]

logger = logging.getLogger(__name__)

# Retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0  # seconds
DEFAULT_RETRY_BACKOFF = 2.0  # multiplier


@dataclass
class ServerStatus:
    """Status information for an MCP server."""

    name: str
    connected: bool
    tool_count: int
    cache_enabled: bool
    needs_setup: bool = False  # True if credentials_path is set but doesn't exist
    enabled: bool = True  # Whether server auto-connects at startup
    error: str | None = None


@dataclass
class MCPToolManager:
    """Manages multiple MCP server connections.

    Provides a unified interface for connecting to servers, discovering tools,
    and routing tool invocations to the appropriate server.

    Usage:
        manager = MCPToolManager()
        await manager.connect_servers(config)
        try:
            schemas = await manager.get_tool_schemas()
            result = await manager.call_tool("mcp_sqlite_query", {"sql": "SELECT 1"})
        finally:
            await manager.disconnect_all()

    Or as async context manager:
        async with MCPToolManager() as manager:
            await manager.connect_servers(config)
            ...
    """

    _clients: dict[str, MCPClient] = field(default_factory=dict, init=False)
    _tool_to_server: dict[str, str] = field(default_factory=dict, init=False)
    _config: MCPConfig | None = field(default=None, init=False)

    async def connect_servers(self, config: MCPConfig) -> dict[str, str | None]:
        """Connect to all enabled servers in the configuration.

        Connections are attempted in parallel. Servers that fail to connect
        are logged but do not prevent other servers from connecting.

        Args:
            config: MCP configuration with server definitions.

        Returns:
            Dictionary mapping server names to error messages (None if successful).
        """
        self._config = config
        enabled = config.get_enabled_servers()

        if not enabled:
            logger.debug("No MCP servers enabled in configuration")
            return {}

        results: dict[str, str | None] = {}

        # Connect to servers in parallel
        async def connect_one(
            name: str, server_config: MCPServerConfig
        ) -> tuple[str, str | None]:
            try:
                client = MCPClient(config=server_config)
                await client.connect()
                self._clients[name] = client

                # Update tool-to-server mapping
                for tool in client.tools:
                    self._tool_to_server[tool.name] = name

                logger.info(
                    f"Connected to MCP server '{name}' with {len(client.tools)} tools"
                )
                return (name, None)
            except MCPConnectionError as e:
                logger.warning(f"Failed to connect to MCP server '{name}': {e}")
                return (name, str(e))
            except Exception as e:
                logger.exception(f"Unexpected error connecting to MCP server '{name}'")
                return (name, str(e))

        # Run connections in parallel
        tasks = [connect_one(name, cfg) for name, cfg in enabled.items()]
        for coro in asyncio.as_completed(tasks):
            name, error = await coro
            results[name] = error

        return results

    async def connect_server(
        self,
        server_name: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> None:
        """Connect to a specific server with retry logic.

        Args:
            server_name: Name of the server to connect to.
            max_retries: Maximum number of connection attempts.
            retry_delay: Initial delay between retries (doubles each attempt).

        Raises:
            ValueError: If server is not in configuration.
            MCPConnectionError: If all connection attempts fail.
        """
        if not self._config:
            raise ValueError("No configuration loaded. Call connect_servers() first.")

        if server_name not in self._config.servers:
            raise ValueError(f"Server '{server_name}' not in configuration")

        server_config = self._config.servers[server_name]

        # Disconnect existing client if any
        if server_name in self._clients:
            await self.disconnect_server(server_name)

        last_error: Exception | None = None
        delay = retry_delay

        for attempt in range(max_retries):
            try:
                client = MCPClient(config=server_config)
                await client.connect()
                self._clients[server_name] = client

                # Update tool-to-server mapping
                for tool in client.tools:
                    self._tool_to_server[tool.name] = server_name

                logger.info(
                    f"Connected to MCP server '{server_name}' with {len(client.tools)} tools"
                )
                return

            except MCPTimeoutError as e:
                last_error = e
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Timeout connecting to '{server_name}' "
                        f"(attempt {attempt + 1}/{max_retries}), retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    delay *= DEFAULT_RETRY_BACKOFF

            except MCPConnectionError as e:
                last_error = e
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Failed to connect to '{server_name}' "
                        f"(attempt {attempt + 1}/{max_retries}): {e}, retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    delay *= DEFAULT_RETRY_BACKOFF

        # All retries exhausted
        raise MCPConnectionError(
            f"Failed to connect to MCP server '{server_name}' after {max_retries} attempts: {last_error}"
        ) from last_error

    async def disconnect_server(self, server_name: str) -> None:
        """Disconnect from a specific server.

        Args:
            server_name: Name of the server to disconnect from.
        """
        if server_name not in self._clients:
            return

        client = self._clients[server_name]

        # Remove tools from mapping
        tools_to_remove = [
            tool_name
            for tool_name, srv in self._tool_to_server.items()
            if srv == server_name
        ]
        for tool_name in tools_to_remove:
            del self._tool_to_server[tool_name]

        await client.disconnect()
        del self._clients[server_name]
        logger.info(f"Disconnected from MCP server '{server_name}'")

    async def disconnect_all(self) -> None:
        """Disconnect from all connected servers."""
        server_names = list(self._clients.keys())
        for name in server_names:
            try:
                await self.disconnect_server(name)
            except Exception as e:
                logger.warning(f"Error disconnecting from '{name}': {e}")

    async def get_tool_schemas(
        self, force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """Get Anthropic-compatible tool schemas for all connected servers.

        Args:
            force_refresh: If True, fetch fresh schemas from all servers.

        Returns:
            List of tool schemas in Anthropic format.
        """
        schemas = []

        for name, client in self._clients.items():
            try:
                # For servers with cache disabled, always refresh
                should_refresh = force_refresh or not client.config.cache
                tools = await client.list_tools(force_refresh=should_refresh)

                # Update tool-to-server mapping
                for tool in tools:
                    self._tool_to_server[tool.name] = name

                # Convert to Anthropic format
                for tool in tools:
                    schemas.append(tool.to_anthropic_schema())

            except Exception as e:
                logger.warning(f"Failed to get tools from server '{name}': {e}")

        return schemas

    async def call_tool(
        self,
        prefixed_tool_name: str,
        arguments: dict[str, Any],
        auto_reconnect: bool = True,
    ) -> Any:
        """Invoke a tool by its prefixed name.

        Args:
            prefixed_tool_name: Tool name with server prefix (e.g., "mcp_sqlite_query").
            arguments: Arguments to pass to the tool.
            auto_reconnect: If True, attempt to reconnect if server has crashed.

        Returns:
            Tool execution result.

        Raises:
            MCPToolError: If tool not found or invocation fails.
        """
        # Look up which server owns this tool
        server_name = self._tool_to_server.get(prefixed_tool_name)
        if not server_name:
            raise MCPToolError(f"Unknown MCP tool: {prefixed_tool_name}")

        client = self._clients.get(server_name)
        if not client:
            raise MCPToolError(f"Server '{server_name}' not connected")

        # Get the original tool name
        tool = client.get_tool_by_prefixed_name(prefixed_tool_name)
        if not tool:
            raise MCPToolError(
                f"Tool '{prefixed_tool_name}' not found on server '{server_name}'"
            )

        try:
            return await client.call_tool(tool.original_name, arguments)
        except MCPServerCrashedError as e:
            if auto_reconnect:
                logger.warning(
                    f"Server '{server_name}' crashed, attempting reconnect..."
                )
                try:
                    await self.connect_server(server_name)
                    # Retry the tool call after reconnect
                    client = self._clients.get(server_name)
                    if client:
                        return await client.call_tool(tool.original_name, arguments)
                except MCPConnectionError as reconnect_error:
                    raise MCPToolError(
                        f"Server '{server_name}' crashed and reconnection failed: {reconnect_error}"
                    ) from e
            raise

    async def call_tool_on_server(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        """Invoke a tool on a specific server.

        Args:
            server_name: Name of the server to call.
            tool_name: Name of the tool to invoke (original, not prefixed).
            arguments: Arguments to pass to the tool.

        Returns:
            Tool execution result.

        Raises:
            MCPToolError: If server not connected or tool invocation fails.
        """
        client = self._clients.get(server_name)
        if not client:
            raise MCPToolError(f"Server '{server_name}' not connected")

        return await client.call_tool(tool_name, arguments)

    def get_server_for_tool(self, prefixed_tool_name: str) -> str | None:
        """Get the server name for a prefixed tool name.

        Args:
            prefixed_tool_name: Tool name with server prefix (e.g., "mcp_sqlite_query").

        Returns:
            Server name if found, None otherwise.
        """
        return self._tool_to_server.get(prefixed_tool_name)

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool name is an MCP tool.

        Args:
            tool_name: Tool name to check.

        Returns:
            True if tool is from an MCP server.
        """
        return tool_name in self._tool_to_server

    async def refresh_schemas(self, server_name: str | None = None) -> None:
        """Force refresh tool schemas from server(s).

        Args:
            server_name: Specific server to refresh, or None for all.
        """
        if server_name:
            if server_name not in self._clients:
                raise ValueError(f"Server '{server_name}' not connected")
            clients = [(server_name, self._clients[server_name])]
        else:
            clients = list(self._clients.items())

        for name, client in clients:
            try:
                tools = await client.list_tools(force_refresh=True)
                # Update mapping
                for tool in tools:
                    self._tool_to_server[tool.name] = name
                logger.info(f"Refreshed {len(tools)} tools from server '{name}'")
            except Exception as e:
                logger.warning(f"Failed to refresh tools from '{name}': {e}")

    def set_cache_enabled(self, server_name: str, enabled: bool) -> None:
        """Toggle caching for a specific server.

        Args:
            server_name: Server to configure.
            enabled: Whether to enable caching.

        Raises:
            ValueError: If server not found.
        """
        if server_name not in self._clients:
            raise ValueError(f"Server '{server_name}' not connected")

        client = self._clients[server_name]
        client.config.cache = enabled
        logger.info(f"Set cache={enabled} for server '{server_name}'")

    def get_cache_enabled(self, server_name: str) -> bool:
        """Get caching status for a server.

        Args:
            server_name: Server to check.

        Returns:
            Whether caching is enabled.

        Raises:
            ValueError: If server not found.
        """
        if server_name not in self._clients:
            raise ValueError(f"Server '{server_name}' not connected")

        return self._clients[server_name].config.cache

    def get_server_status(self) -> list[ServerStatus]:
        """Get status information for all configured servers.

        Returns:
            List of ServerStatus objects.
        """
        if not self._config:
            return []

        statuses = []
        for name, server_config in self._config.servers.items():
            client = self._clients.get(name)
            connected = client is not None and client.is_connected
            tool_count = len(client.tools) if client else 0

            statuses.append(
                ServerStatus(
                    name=name,
                    connected=connected,
                    tool_count=tool_count,
                    cache_enabled=server_config.cache,
                    needs_setup=server_config.needs_setup(),
                    enabled=server_config.enabled,
                    error=None,
                )
            )

        return statuses

    def get_connected_server_names(self) -> list[str]:
        """Get names of all connected servers.

        Returns:
            List of server names.
        """
        return [name for name, client in self._clients.items() if client.is_connected]

    def get_all_tools(self) -> list[MCPToolInfo]:
        """Get all tools from all connected servers.

        Returns:
            List of MCPToolInfo objects.
        """
        tools = []
        for client in self._clients.values():
            tools.extend(client.tools)
        return tools

    def format_error_as_tool_result(self, error: Exception, tool_name: str) -> str:
        """Format an MCP error as a tool result message.

        Translates MCP errors to user-friendly messages suitable for
        returning as tool results to the agent.

        Args:
            error: The exception that occurred.
            tool_name: Name of the tool that was being called.

        Returns:
            Formatted error message.
        """
        if isinstance(error, MCPTimeoutError):
            return (
                f"Error: Tool '{tool_name}' timed out. "
                "The operation took too long to complete. "
                "Consider retrying or breaking down the request."
            )
        elif isinstance(error, MCPServerCrashedError):
            return (
                f"Error: The MCP server handling '{tool_name}' has crashed. "
                "The server will be automatically restarted on the next request."
            )
        elif isinstance(error, MCPConnectionError):
            return (
                f"Error: Cannot connect to the server for '{tool_name}'. "
                "The server may be unavailable or misconfigured."
            )
        elif isinstance(error, MCPToolError):
            return f"Error: {error}"
        else:
            return f"Error calling '{tool_name}': {error}"

    async def health_check(self) -> dict[str, bool]:
        """Check health of all connected servers.

        Attempts to list tools from each server to verify connectivity.

        Returns:
            Dictionary mapping server names to health status (True = healthy).
        """
        results = {}
        for name, client in self._clients.items():
            try:
                await client.list_tools(force_refresh=True)
                results[name] = True
            except Exception as e:
                logger.warning(f"Health check failed for '{name}': {e}")
                results[name] = False
        return results

    async def __aenter__(self) -> "MCPToolManager":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - disconnect all servers."""
        await self.disconnect_all()
