"""Integration tests for MCP with mock MCP server.

Tests end-to-end MCP functionality using a mock server process.
"""

import json
from unittest.mock import MagicMock

import pytest

from silica.developer.mcp.client import MCPClient
from silica.developer.mcp.config import MCPConfig, MCPServerConfig
from silica.developer.mcp.manager import MCPToolManager


class MockTextContent:
    """Mock TextContent that matches MCP SDK structure."""

    def __init__(self, text: str):
        self.text = text
        self.type = "text"


class MockMCPServerSession:
    """Mock MCP server session for testing."""

    def __init__(self, tools: list[dict]):
        self.tools = tools
        self._initialized = False

    async def initialize(self):
        """Mock initialize handshake."""
        self._initialized = True
        # Return mock init result
        result = MagicMock()
        result.protocolVersion = "1.0"
        result.serverInfo = MagicMock()
        result.serverInfo.name = "mock_server"
        return result

    async def list_tools(self):
        """Return mock tools."""
        result = MagicMock()
        result.tools = []
        for tool_def in self.tools:
            mock_tool = MagicMock()
            mock_tool.name = tool_def["name"]
            mock_tool.description = tool_def.get("description", "")
            mock_tool.inputSchema = tool_def.get("inputSchema", {"type": "object"})
            result.tools.append(mock_tool)
        return result

    async def call_tool(self, name: str, arguments: dict):
        """Mock tool call."""
        from mcp.types import TextContent

        # Find tool and return appropriate response
        for tool_def in self.tools:
            if tool_def["name"] == name:
                # Call handler if provided
                if "handler" in tool_def:
                    content = tool_def["handler"](arguments)
                else:
                    content = f"Called {name} with {arguments}"

                # Create mock result with real TextContent
                result = MagicMock()
                result.isError = False
                result.content = [TextContent(type="text", text=content)]
                return result

        # Tool not found
        raise ValueError(f"Unknown tool: {name}")


def create_mock_mcp_client(tools: list[dict]) -> tuple[MCPClient, MockMCPServerSession]:
    """Create an MCPClient with a mock session."""
    config = MCPServerConfig(
        name="mock",
        command="python",
        args=["-c", "pass"],  # Dummy command
    )
    client = MCPClient(config=config)

    # Create mock session
    session = MockMCPServerSession(tools)
    client._session = session
    client._connected = True
    client._read_stream = MagicMock()
    client._write_stream = MagicMock()

    return client, session


class TestMCPClientIntegration:
    """Integration tests for MCPClient with mock session."""

    @pytest.mark.asyncio
    async def test_list_tools_with_mock_session(self):
        """Test listing tools from mock session."""
        tools = [
            {
                "name": "echo",
                "description": "Echo input",
                "inputSchema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                },
            },
            {
                "name": "add",
                "description": "Add numbers",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                },
            },
        ]

        client, _ = create_mock_mcp_client(tools)

        result = await client.list_tools()

        assert len(result) == 2
        assert result[0].original_name == "echo"
        assert result[1].original_name == "add"
        # Tools should be prefixed
        assert result[0].name == "mcp_mock_echo"
        assert result[1].name == "mcp_mock_add"

    @pytest.mark.asyncio
    async def test_call_tool_with_mock_session(self):
        """Test calling tools on mock session."""
        tools = [
            {
                "name": "greet",
                "description": "Greet someone",
                "handler": lambda args: f"Hello, {args.get('name', 'World')}!",
            }
        ]

        client, _ = create_mock_mcp_client(tools)

        # Fetch tools first to populate cache
        await client.list_tools()

        result = await client.call_tool("greet", {"name": "Alice"})

        assert result == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_call_tool_with_complex_handler(self):
        """Test tool with complex handler logic."""
        call_log = []

        def calculator_handler(args):
            call_log.append(args)
            op = args.get("operation", "add")
            a = args.get("a", 0)
            b = args.get("b", 0)
            if op == "add":
                return str(a + b)
            elif op == "multiply":
                return str(a * b)
            return "unknown operation"

        tools = [
            {
                "name": "calculator",
                "description": "Simple calculator",
                "handler": calculator_handler,
            }
        ]

        client, _ = create_mock_mcp_client(tools)
        await client.list_tools()

        result1 = await client.call_tool(
            "calculator", {"operation": "add", "a": 2, "b": 3}
        )
        result2 = await client.call_tool(
            "calculator", {"operation": "multiply", "a": 4, "b": 5}
        )

        assert result1 == "5"
        assert result2 == "20"
        assert len(call_log) == 2


class TestMCPManagerIntegration:
    """Integration tests for MCPToolManager with multiple mock servers."""

    @pytest.mark.asyncio
    async def test_multiple_servers(self):
        """Test manager with multiple mock servers."""
        manager = MCPToolManager()

        # Create mock clients for two servers
        db_client, _ = create_mock_mcp_client(
            [
                {
                    "name": "query",
                    "description": "Run SQL query",
                    "handler": lambda args: f"Query result: {args.get('sql', '')}",
                }
            ]
        )
        db_client.config.name = "database"

        fs_client, _ = create_mock_mcp_client(
            [
                {
                    "name": "read",
                    "description": "Read file",
                    "handler": lambda args: f"File contents: {args.get('path', '')}",
                }
            ]
        )
        fs_client.config.name = "filesystem"

        # Manually set up manager
        manager._clients["database"] = db_client
        manager._clients["filesystem"] = fs_client

        # Fetch and register tools
        for name, client in manager._clients.items():
            tools = await client.list_tools()
            for tool in tools:
                manager._tool_to_server[tool.name] = name

        # Test calling tools from different servers
        db_result = await manager.call_tool(
            "mcp_database_query", {"sql": "SELECT * FROM users"}
        )
        fs_result = await manager.call_tool(
            "mcp_filesystem_read", {"path": "/etc/config"}
        )

        assert "Query result" in db_result
        assert "SELECT * FROM users" in db_result
        assert "File contents" in fs_result
        assert "/etc/config" in fs_result

    @pytest.mark.asyncio
    async def test_tool_schema_aggregation(self):
        """Test that schemas from multiple servers are aggregated."""
        manager = MCPToolManager()

        # Create clients with different tools
        client1, _ = create_mock_mcp_client(
            [{"name": "tool_a", "description": "Tool A"}]
        )
        client1.config.name = "server1"

        client2, _ = create_mock_mcp_client(
            [
                {"name": "tool_b", "description": "Tool B"},
                {"name": "tool_c", "description": "Tool C"},
            ]
        )
        client2.config.name = "server2"

        manager._clients["server1"] = client1
        manager._clients["server2"] = client2

        schemas = await manager.get_tool_schemas()

        assert len(schemas) == 3
        names = {s["name"] for s in schemas}
        assert "mcp_server1_tool_a" in names
        assert "mcp_server2_tool_b" in names
        assert "mcp_server2_tool_c" in names


class TestEndToEndWorkflow:
    """End-to-end workflow tests."""

    @pytest.mark.asyncio
    async def test_connect_list_call_disconnect_workflow(self):
        """Test full workflow: connect → list tools → call → disconnect."""
        config = MCPServerConfig(
            name="workflow_test",
            command="python",
            args=["-c", "pass"],
        )

        client = MCPClient(config=config)

        # Mock the connection
        async def mock_connect(self, *args, **kwargs):
            self._connected = True
            self._session = MockMCPServerSession(
                [
                    {
                        "name": "process",
                        "description": "Process data",
                        "handler": lambda args: f"Processed: {args.get('data', '')}",
                    }
                ]
            )
            self._read_stream = MagicMock()
            self._write_stream = MagicMock()
            await self._session.initialize()

        # Replace connect method
        client.connect = lambda *a, **k: mock_connect(client, *a, **k)

        # Workflow
        await client.connect()
        assert client.is_connected

        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].original_name == "process"

        result = await client.call_tool("process", {"data": "hello"})
        assert result == "Processed: hello"

        await client.disconnect()
        assert not client.is_connected

    @pytest.mark.asyncio
    async def test_manager_context_manager_workflow(self):
        """Test manager as context manager."""
        manager = MCPToolManager()

        # Add a mock client
        client, _ = create_mock_mcp_client(
            [{"name": "test_tool", "description": "Test"}]
        )
        manager._clients["test"] = client

        async with manager:
            # Inside context, client should be accessible
            assert "test" in manager._clients

        # After context, clients should be disconnected
        # (disconnect_all was called)
        assert len(manager._clients) == 0

    @pytest.mark.asyncio
    async def test_tool_not_found_error(self):
        """Test error handling for unknown tool."""
        manager = MCPToolManager()

        client, _ = create_mock_mcp_client([{"name": "known_tool"}])
        manager._clients["test"] = client
        manager._tool_to_server["mcp_test_known_tool"] = "test"

        from silica.developer.mcp.client import MCPToolError

        with pytest.raises(MCPToolError) as exc_info:
            await manager.call_tool("mcp_test_unknown_tool", {})

        assert "Unknown MCP tool" in str(exc_info.value)


class TestConfigToClientWorkflow:
    """Test workflows from config to working client."""

    def test_config_creates_correct_server_params(self):
        """Test that config correctly maps to server parameters."""
        config = MCPServerConfig.from_dict(
            "myserver",
            {
                "command": "uvx",
                "args": ["mcp-server-test", "--db", "/tmp/test.db"],
                "env": {"DEBUG": "1"},
                "enabled": True,
                "cache": False,
            },
        )

        assert config.name == "myserver"
        assert config.command == "uvx"
        assert config.args == ["mcp-server-test", "--db", "/tmp/test.db"]
        assert config.env == {"DEBUG": "1"}
        assert config.enabled is True
        assert config.cache is False

    def test_full_config_loading(self, tmp_path):
        """Test loading full MCP config from file."""
        config_file = tmp_path / "mcp_servers.json"
        config_file.write_text(
            json.dumps(
                {
                    "servers": {
                        "sqlite": {
                            "command": "uvx",
                            "args": ["mcp-server-sqlite"],
                            "enabled": True,
                        },
                        "disabled_server": {
                            "command": "python",
                            "args": ["server.py"],
                            "enabled": False,
                        },
                    }
                }
            )
        )

        config = MCPConfig.from_file(config_file)

        assert len(config.servers) == 2
        assert "sqlite" in config.servers
        assert config.servers["sqlite"].enabled is True
        assert config.servers["disabled_server"].enabled is False

        # Only enabled servers should be in get_enabled_servers
        enabled = config.get_enabled_servers()
        assert len(enabled) == 1
        assert "sqlite" in enabled


class TestCachingBehavior:
    """Test tool schema caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_enabled_reuses_tools(self):
        """Test that cache=True reuses tool list."""
        tools = [{"name": "cached_tool"}]
        client, session = create_mock_mcp_client(tools)
        client.config.cache = True

        # First call
        result1 = await client.list_tools()

        # Modify session tools (simulating server change)
        session.tools = [{"name": "new_tool"}]

        # Second call should return cached result
        result2 = await client.list_tools()

        assert result1[0].original_name == "cached_tool"
        assert result2[0].original_name == "cached_tool"  # Still cached

    @pytest.mark.asyncio
    async def test_cache_disabled_always_fetches(self):
        """Test that cache=False always fetches fresh tools."""
        tools = [{"name": "tool_v1"}]
        client, session = create_mock_mcp_client(tools)
        client.config.cache = False

        # First call
        result1 = await client.list_tools()

        # Modify session tools
        session.tools = [{"name": "tool_v2"}]

        # Second call should get fresh result
        result2 = await client.list_tools()

        assert result1[0].original_name == "tool_v1"
        assert result2[0].original_name == "tool_v2"

    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_cache(self):
        """Test that force_refresh=True bypasses cache."""
        tools = [{"name": "tool_v1"}]
        client, session = create_mock_mcp_client(tools)
        client.config.cache = True

        # First call with caching
        result1 = await client.list_tools()

        # Modify session tools
        session.tools = [{"name": "tool_v2"}]

        # Force refresh should get new tools
        result2 = await client.list_tools(force_refresh=True)

        assert result1[0].original_name == "tool_v1"
        assert result2[0].original_name == "tool_v2"
