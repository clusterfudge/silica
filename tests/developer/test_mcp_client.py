"""Tests for MCP Client wrapper."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from silica.developer.mcp.client import (
    MCPClient,
    MCPConnectionError,
    MCPToolInfo,
)
from silica.developer.mcp.config import MCPServerConfig


@pytest.fixture
def server_config():
    """Create a test server config."""
    return MCPServerConfig(
        name="test_server",
        command="python",
        args=["-m", "test_server"],
        env={"TEST": "value"},
        enabled=True,
        cache=True,
    )


@pytest.fixture
def client(server_config):
    """Create a test client."""
    return MCPClient(config=server_config)


class TestMCPToolInfo:
    """Tests for MCPToolInfo dataclass."""

    def test_to_anthropic_schema(self):
        """Test conversion to Anthropic schema format."""
        tool = MCPToolInfo(
            name="mcp_server_query",
            description="Run a query",
            input_schema={"type": "object", "properties": {"sql": {"type": "string"}}},
            server_name="server",
            original_name="query",
        )
        schema = tool.to_anthropic_schema()
        assert schema["name"] == "mcp_server_query"
        assert schema["description"] == "Run a query"
        assert "input_schema" in schema


class TestMCPClientProperties:
    """Tests for MCPClient properties."""

    def test_server_name(self, client, server_config):
        """Test server_name property."""
        assert client.server_name == "test_server"

    def test_is_connected_default(self, client):
        """Test is_connected defaults to False."""
        assert client.is_connected is False

    def test_tools_default_empty(self, client):
        """Test tools defaults to empty list."""
        assert client.tools == []


class TestMCPClientToolLookup:
    """Tests for tool lookup methods."""

    def test_get_tool_by_original_name(self, client):
        """Test finding tool by original name."""
        client._tools = [
            MCPToolInfo(
                name="mcp_server_query",
                description="desc",
                input_schema={},
                server_name="server",
                original_name="query",
            )
        ]
        tool = client.get_tool_by_original_name("query")
        assert tool is not None
        assert tool.name == "mcp_server_query"

    def test_get_tool_by_original_name_not_found(self, client):
        """Test tool not found returns None."""
        client._tools = []
        assert client.get_tool_by_original_name("nonexistent") is None

    def test_get_tool_by_prefixed_name(self, client):
        """Test finding tool by prefixed name."""
        client._tools = [
            MCPToolInfo(
                name="mcp_server_query",
                description="desc",
                input_schema={},
                server_name="server",
                original_name="query",
            )
        ]
        tool = client.get_tool_by_prefixed_name("mcp_server_query")
        assert tool is not None
        assert tool.original_name == "query"


class TestMCPClientListToolsErrors:
    """Tests for list_tools error handling."""

    @pytest.mark.asyncio
    async def test_list_tools_not_connected(self, client):
        """Test list_tools raises when not connected."""
        with pytest.raises(MCPConnectionError, match="Not connected"):
            await client.list_tools()


class TestMCPClientCallToolErrors:
    """Tests for call_tool error handling."""

    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self, client):
        """Test call_tool raises when not connected."""
        with pytest.raises(MCPConnectionError, match="Not connected"):
            await client.call_tool("some_tool", {})


class TestMCPClientResultExtraction:
    """Tests for result content extraction."""

    def test_extract_single_text_content(self, client):
        """Test extracting single text content."""
        from mcp.types import CallToolResult, TextContent

        result = CallToolResult(
            content=[TextContent(type="text", text="Hello World")],
            isError=False,
        )
        extracted = client._extract_result_content(result)
        assert extracted == "Hello World"

    def test_extract_multiple_content(self, client):
        """Test extracting multiple content items."""
        from mcp.types import CallToolResult, TextContent

        result = CallToolResult(
            content=[
                TextContent(type="text", text="Line 1"),
                TextContent(type="text", text="Line 2"),
            ],
            isError=False,
        )
        extracted = client._extract_result_content(result)
        assert extracted == ["Line 1", "Line 2"]

    def test_extract_empty_content(self, client):
        """Test extracting empty content returns None."""
        from mcp.types import CallToolResult

        result = CallToolResult(content=[], isError=False)
        extracted = client._extract_result_content(result)
        assert extracted is None


class TestMCPClientConnection:
    """Tests for connection lifecycle (mocked)."""

    @pytest.mark.asyncio
    async def test_connect_success(self, client):
        """Test successful connection."""
        # Mock the MCP SDK
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock(
            return_value=MagicMock(
                protocolVersion="1.0",
                serverInfo=MagicMock(name="TestServer"),
            )
        )

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
        mock_context.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "silica.developer.mcp.client.stdio_client", return_value=mock_context
        ):
            with patch(
                "silica.developer.mcp.client.ClientSession", return_value=mock_session
            ):
                await client.connect()
                assert client.is_connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(self, client):
        """Test connection failure raises MCPConnectionError."""
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
        mock_context.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "silica.developer.mcp.client.stdio_client", return_value=mock_context
        ):
            with pytest.raises(MCPConnectionError, match="Failed to connect"):
                await client.connect()
            assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self, client):
        """Test disconnect cleans up properly."""
        # Set up as if connected
        client._connected = True
        client._session = MagicMock()
        client._context_manager = AsyncMock()
        client._context_manager.__aexit__ = AsyncMock(return_value=None)
        client._tools = [MagicMock()]

        await client.disconnect()

        assert client.is_connected is False
        assert client._session is None
        assert client._tools == []

    @pytest.mark.asyncio
    async def test_connect_when_already_connected(self, client):
        """Test connect is no-op when already connected."""
        client._connected = True
        # Should not raise or do anything
        await client.connect()
        assert client.is_connected is True


class TestMCPClientListTools:
    """Tests for list_tools with mocked session."""

    @pytest.mark.asyncio
    async def test_list_tools_success(self, client):
        """Test listing tools from server."""
        from mcp.types import Tool

        # Set up as connected
        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=MagicMock(
                tools=[
                    Tool(
                        name="query",
                        description="Run SQL",
                        inputSchema={"type": "object"},
                    )
                ]
            )
        )
        client._connected = True
        client._session = mock_session

        tools = await client.list_tools()

        assert len(tools) == 1
        assert tools[0].original_name == "query"
        assert tools[0].name == "mcp_test_server_query"
        assert tools[0].server_name == "test_server"

    @pytest.mark.asyncio
    async def test_list_tools_cached(self, client):
        """Test that tools are cached when cache=True."""
        client._connected = True
        client._session = AsyncMock()
        client._tools = [
            MCPToolInfo(
                name="cached",
                description="",
                input_schema={},
                server_name="test",
                original_name="cached",
            )
        ]

        # Should return cached without calling session
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "cached"
        client._session.list_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_tools_force_refresh(self, client):
        """Test force_refresh bypasses cache."""
        from mcp.types import Tool

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=MagicMock(
                tools=[
                    Tool(
                        name="new_tool",
                        description="New",
                        inputSchema={"type": "object"},
                    )
                ]
            )
        )
        client._connected = True
        client._session = mock_session
        client._tools = [MagicMock()]  # Existing cached tools

        tools = await client.list_tools(force_refresh=True)

        assert len(tools) == 1
        assert tools[0].original_name == "new_tool"
        mock_session.list_tools.assert_called_once()
