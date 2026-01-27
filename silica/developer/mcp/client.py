"""MCP Client wrapper around the official MCP SDK.

Provides a simplified interface for connecting to MCP servers,
listing tools, and invoking tool calls.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent

from silica.developer.mcp.config import MCPServerConfig
from silica.developer.mcp.schema import mcp_to_anthropic_schema

__all__ = [
    "MCPClient",
    "MCPToolInfo",
    "MCPConnectionError",
    "MCPToolError",
    "MCPTimeoutError",
    "MCPServerCrashedError",
]

logger = logging.getLogger(__name__)

# Default timeouts (in seconds)
DEFAULT_CONNECT_TIMEOUT = 30.0
DEFAULT_TOOL_TIMEOUT = 60.0
DEFAULT_LIST_TOOLS_TIMEOUT = 15.0


class MCPConnectionError(Exception):
    """Raised when connection to MCP server fails."""


class MCPToolError(Exception):
    """Raised when MCP tool invocation fails."""

    def __init__(self, message: str, is_error: bool = True, tool_name: str = None):
        super().__init__(message)
        self.is_error = is_error
        self.tool_name = tool_name


class MCPTimeoutError(MCPToolError):
    """Raised when an MCP operation times out."""


class MCPServerCrashedError(MCPConnectionError):
    """Raised when the MCP server process has terminated unexpectedly."""


@dataclass
class MCPToolInfo:
    """Information about a tool exposed by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str  # Which server this tool belongs to
    original_name: str  # Original name before prefixing

    def to_anthropic_schema(self) -> dict[str, Any]:
        """Convert to Anthropic tool schema format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class MCPClient:
    """Client for connecting to a single MCP server.

    Wraps the MCP SDK's ClientSession and provides methods for
    tool discovery and invocation.

    Usage:
        client = MCPClient(config)
        await client.connect()
        try:
            tools = await client.list_tools()
            result = await client.call_tool("tool_name", {"arg": "value"})
        finally:
            await client.disconnect()
    """

    config: MCPServerConfig
    _connected: bool = field(default=False, init=False)
    _tools: list[MCPToolInfo] = field(default_factory=list, init=False)
    _session: ClientSession | None = field(default=None, init=False)
    _read_stream: Any = field(default=None, init=False)
    _write_stream: Any = field(default=None, init=False)
    _stdio_context: Any = field(default=None, init=False)
    _session_context: Any = field(default=None, init=False)

    async def connect(self, timeout: float = DEFAULT_CONNECT_TIMEOUT) -> None:
        """Connect to the MCP server and perform capability negotiation.

        Args:
            timeout: Maximum time to wait for connection (in seconds).

        Raises:
            MCPConnectionError: If connection fails.
            MCPTimeoutError: If connection times out.
        """
        if self._connected:
            return

        try:
            # Create server parameters
            server_params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args,
                env=self.config.env if self.config.env else None,
            )

            # Create stdio transport - use context manager properly
            self._stdio_context = stdio_client(server_params)

            try:
                (
                    self._read_stream,
                    self._write_stream,
                ) = await asyncio.wait_for(
                    self._stdio_context.__aenter__(), timeout=timeout
                )
            except asyncio.TimeoutError:
                raise MCPTimeoutError(
                    f"Timeout connecting to MCP server '{self.config.name}' "
                    f"after {timeout}s"
                )

            # Create session and use it as a context manager
            # The MCP SDK requires ClientSession to be used with async with
            self._session_context = ClientSession(self._read_stream, self._write_stream)
            try:
                self._session = await asyncio.wait_for(
                    self._session_context.__aenter__(), timeout=timeout
                )
            except asyncio.TimeoutError:
                raise MCPTimeoutError(
                    f"Timeout creating session with '{self.config.name}' "
                    f"after {timeout}s"
                )

            # Initialize the session (runs the protocol handshake) with timeout
            try:
                init_result = await asyncio.wait_for(
                    self._session.initialize(), timeout=timeout
                )
            except asyncio.TimeoutError:
                raise MCPTimeoutError(
                    f"Timeout during MCP handshake with '{self.config.name}' "
                    f"after {timeout}s"
                )

            logger.info(
                f"Connected to MCP server '{self.config.name}': "
                f"protocol={init_result.protocolVersion}, "
                f"server={init_result.serverInfo.name if init_result.serverInfo else 'unknown'}"
            )

            self._connected = True

            # Fetch initial tool list if caching is enabled
            if self.config.cache:
                await self.list_tools()

        except MCPTimeoutError:
            await self._cleanup()
            raise
        except Exception as e:
            # Clean up on failure
            await self._cleanup()
            raise MCPConnectionError(
                f"Failed to connect to MCP server '{self.config.name}': {e}"
            ) from e

    async def _cleanup(self) -> None:
        """Clean up connection resources."""
        # Exit session context first
        if self._session_context:
            try:
                await self._session_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_context = None

        self._session = None

        # Then exit stdio context
        if self._stdio_context:
            try:
                await self._stdio_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._stdio_context = None

        self._read_stream = None
        self._write_stream = None
        self._connected = False

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if not self._connected:
            return

        logger.info(f"Disconnecting from MCP server '{self.config.name}'")
        await self._cleanup()
        self._tools = []

    async def list_tools(
        self, force_refresh: bool = False, timeout: float = DEFAULT_LIST_TOOLS_TIMEOUT
    ) -> list[MCPToolInfo]:
        """List tools available from this server.

        Args:
            force_refresh: If True, fetch fresh tool list even if cached.
            timeout: Maximum time to wait for response (in seconds).

        Returns:
            List of available tools.

        Raises:
            MCPConnectionError: If not connected.
            MCPToolError: If listing tools fails.
            MCPTimeoutError: If request times out.
        """
        if not self._connected or not self._session:
            raise MCPConnectionError(
                f"Not connected to MCP server '{self.config.name}'"
            )

        # Return cached tools if available and not forcing refresh
        if self._tools and not force_refresh and self.config.cache:
            return self._tools

        try:
            try:
                result = await asyncio.wait_for(
                    self._session.list_tools(), timeout=timeout
                )
            except asyncio.TimeoutError:
                raise MCPTimeoutError(
                    f"Timeout listing tools from '{self.config.name}' after {timeout}s"
                )

            # Convert MCP tools to our format
            tools = []
            for mcp_tool in result.tools:
                # Convert to Anthropic format (includes prefixing)
                anthropic_schema = mcp_to_anthropic_schema(
                    {
                        "name": mcp_tool.name,
                        "description": mcp_tool.description or "",
                        "inputSchema": mcp_tool.inputSchema,
                    },
                    self.config.name,
                )

                tool_info = MCPToolInfo(
                    name=anthropic_schema["name"],
                    description=anthropic_schema["description"],
                    input_schema=anthropic_schema["input_schema"],
                    server_name=self.config.name,
                    original_name=mcp_tool.name,
                )
                tools.append(tool_info)

            self._tools = tools
            logger.debug(
                f"Listed {len(tools)} tools from MCP server '{self.config.name}'"
            )
            return tools

        except MCPTimeoutError:
            raise
        except Exception as e:
            # Check if server crashed
            if self._check_server_crashed():
                raise MCPServerCrashedError(
                    f"MCP server '{self.config.name}' has crashed"
                ) from e
            raise MCPToolError(
                f"Failed to list tools from MCP server '{self.config.name}': {e}"
            ) from e

    def _check_server_crashed(self) -> bool:
        """Check if the server process has crashed.

        Returns:
            True if server appears to have crashed.
        """
        # Check if streams are closed
        if self._read_stream is None or self._write_stream is None:
            return True

        # Check stream state if available
        try:
            # The read stream might have an at_eof() method
            if hasattr(self._read_stream, "at_eof") and self._read_stream.at_eof():
                return True
        except Exception:
            pass

        return False

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = DEFAULT_TOOL_TIMEOUT,
    ) -> Any:
        """Invoke a tool on this server.

        Args:
            tool_name: Name of the tool to call (original name, not prefixed).
            arguments: Arguments to pass to the tool.
            timeout: Maximum time to wait for tool execution (in seconds).

        Returns:
            Tool execution result.

        Raises:
            MCPConnectionError: If not connected.
            MCPToolError: If tool invocation fails.
            MCPTimeoutError: If tool execution times out.
        """
        if not self._connected or not self._session:
            raise MCPConnectionError(
                f"Not connected to MCP server '{self.config.name}'"
            )

        try:
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool(tool_name, arguments), timeout=timeout
                )
            except asyncio.TimeoutError:
                raise MCPTimeoutError(
                    f"Timeout calling tool '{tool_name}' on '{self.config.name}' "
                    f"after {timeout}s",
                    tool_name=tool_name,
                )

            # Check if the result indicates an error
            if result.isError:
                error_content = self._extract_result_content(result)
                raise MCPToolError(
                    f"Tool '{tool_name}' returned error: {error_content}",
                    is_error=True,
                    tool_name=tool_name,
                )

            # Extract content from result
            return self._extract_result_content(result)

        except (MCPTimeoutError, MCPToolError):
            raise
        except Exception as e:
            # Check if server crashed
            if self._check_server_crashed():
                raise MCPServerCrashedError(
                    f"MCP server '{self.config.name}' has crashed during tool call"
                ) from e
            raise MCPToolError(
                f"Failed to call tool '{tool_name}' on server '{self.config.name}': {e}",
                tool_name=tool_name,
            ) from e

    def _extract_result_content(self, result: CallToolResult) -> Any:
        """Extract the content from a CallToolResult.

        Args:
            result: The result from calling a tool.

        Returns:
            Extracted content (text, or structured data).
        """
        if not result.content:
            return None

        # If there's only one content item, return it directly
        if len(result.content) == 1:
            content = result.content[0]
            if isinstance(content, TextContent):
                return content.text
            # Handle other content types (ImageContent, ResourceContent, etc.)
            return (
                content.model_dump() if hasattr(content, "model_dump") else str(content)
            )

        # Multiple content items - return as list
        results = []
        for content in result.content:
            if isinstance(content, TextContent):
                results.append(content.text)
            else:
                results.append(
                    content.model_dump()
                    if hasattr(content, "model_dump")
                    else str(content)
                )
        return results

    async def reconnect(self, timeout: float = DEFAULT_CONNECT_TIMEOUT) -> None:
        """Reconnect to the server.

        Disconnects if connected, then connects again.

        Args:
            timeout: Maximum time to wait for connection (in seconds).
        """
        if self._connected:
            await self.disconnect()
        await self.connect(timeout=timeout)

    @property
    def is_connected(self) -> bool:
        """Whether the client is currently connected."""
        return self._connected

    @property
    def server_name(self) -> str:
        """Name of the server this client connects to."""
        return self.config.name

    @property
    def tools(self) -> list[MCPToolInfo]:
        """Cached list of tools (may be empty if not fetched)."""
        return self._tools

    def get_tool_by_original_name(self, original_name: str) -> MCPToolInfo | None:
        """Get a tool by its original (non-prefixed) name.

        Args:
            original_name: Original tool name.

        Returns:
            MCPToolInfo if found, None otherwise.
        """
        for tool in self._tools:
            if tool.original_name == original_name:
                return tool
        return None

    def get_tool_by_prefixed_name(self, prefixed_name: str) -> MCPToolInfo | None:
        """Get a tool by its prefixed name.

        Args:
            prefixed_name: Prefixed tool name (e.g., "mcp_sqlite_query").

        Returns:
            MCPToolInfo if found, None otherwise.
        """
        for tool in self._tools:
            if tool.name == prefixed_name:
                return tool
        return None
