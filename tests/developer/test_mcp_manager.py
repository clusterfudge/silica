"""Tests for MCP Tool Manager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from silica.developer.mcp.client import MCPClient, MCPConnectionError, MCPToolInfo
from silica.developer.mcp.config import MCPConfig, MCPServerConfig
from silica.developer.mcp.manager import MCPToolManager


@pytest.fixture
def config():
    """Create a test MCP configuration."""
    return MCPConfig(
        servers={
            "sqlite": MCPServerConfig(
                name="sqlite",
                command="uvx",
                args=["mcp-server-sqlite"],
                enabled=True,
                cache=True,
            ),
            "github": MCPServerConfig(
                name="github",
                command="npx",
                args=["mcp-server-github"],
                enabled=True,
                cache=False,
            ),
            "disabled": MCPServerConfig(
                name="disabled",
                command="cmd",
                args=[],
                enabled=False,
            ),
        }
    )


@pytest.fixture
def manager():
    """Create a test manager."""
    return MCPToolManager()


def create_mock_tool(name: str, server: str) -> MCPToolInfo:
    """Create a mock tool info."""
    return MCPToolInfo(
        name=f"mcp_{server}_{name}",
        description=f"Test {name}",
        input_schema={"type": "object"},
        server_name=server,
        original_name=name,
    )


class TestMCPToolManagerConnectServers:
    """Tests for connecting to servers."""

    @pytest.mark.asyncio
    async def test_connect_servers_success(self, manager, config):
        """Test successful connection to all servers."""
        mock_client = MagicMock(spec=MCPClient)
        mock_client.connect = AsyncMock()
        mock_client.tools = [create_mock_tool("query", "sqlite")]
        mock_client.is_connected = True

        with patch("silica.developer.mcp.manager.MCPClient", return_value=mock_client):
            results = await manager.connect_servers(config)

        # Should have attempted 2 enabled servers
        assert "sqlite" in results
        assert "github" in results
        assert "disabled" not in results
        assert results["sqlite"] is None  # No error
        assert results["github"] is None

    @pytest.mark.asyncio
    async def test_connect_servers_partial_failure(self, manager, config):
        """Test that one server failure doesn't prevent others."""
        call_count = 0

        def make_client(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            client = MagicMock(spec=MCPClient)
            client.tools = []
            client.is_connected = True
            if call_count == 1:
                client.connect = AsyncMock(
                    side_effect=MCPConnectionError("Connection refused")
                )
            else:
                client.connect = AsyncMock()
            return client

        with patch("silica.developer.mcp.manager.MCPClient", side_effect=make_client):
            results = await manager.connect_servers(config)

        # One should fail, one should succeed
        errors = [v for v in results.values() if v is not None]
        successes = [v for v in results.values() if v is None]
        assert len(errors) == 1
        assert len(successes) == 1

    @pytest.mark.asyncio
    async def test_connect_no_enabled_servers(self, manager):
        """Test with no enabled servers."""
        config = MCPConfig(servers={})
        results = await manager.connect_servers(config)
        assert results == {}


class TestMCPToolManagerConnectServer:
    """Tests for connecting to a single server."""

    @pytest.mark.asyncio
    async def test_connect_server_no_config(self, manager):
        """Test error when no config loaded."""
        with pytest.raises(ValueError, match="No configuration loaded"):
            await manager.connect_server("sqlite")

    @pytest.mark.asyncio
    async def test_connect_server_not_in_config(self, manager, config):
        """Test error when server not in config."""
        manager._config = config
        with pytest.raises(ValueError, match="not in configuration"):
            await manager.connect_server("nonexistent")

    @pytest.mark.asyncio
    async def test_connect_server_reconnect(self, manager, config):
        """Test reconnecting replaces existing client."""
        manager._config = config

        mock_client = MagicMock(spec=MCPClient)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.tools = []
        mock_client.is_connected = True

        # Set up existing client
        manager._clients["sqlite"] = mock_client

        with patch("silica.developer.mcp.manager.MCPClient", return_value=mock_client):
            await manager.connect_server("sqlite")

        # Should have disconnected old and connected new
        mock_client.disconnect.assert_called_once()


class TestMCPToolManagerDisconnect:
    """Tests for disconnecting."""

    @pytest.mark.asyncio
    async def test_disconnect_server(self, manager):
        """Test disconnecting a single server."""
        mock_client = MagicMock(spec=MCPClient)
        mock_client.disconnect = AsyncMock()
        mock_client.tools = [create_mock_tool("query", "test")]

        manager._clients["test"] = mock_client
        manager._tool_to_server["mcp_test_query"] = "test"

        await manager.disconnect_server("test")

        assert "test" not in manager._clients
        assert "mcp_test_query" not in manager._tool_to_server

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_server(self, manager):
        """Test disconnecting non-existent server is no-op."""
        await manager.disconnect_server("nonexistent")
        # Should not raise

    @pytest.mark.asyncio
    async def test_disconnect_all(self, manager):
        """Test disconnecting all servers."""
        client1 = MagicMock(spec=MCPClient)
        client1.disconnect = AsyncMock()
        client1.tools = []

        client2 = MagicMock(spec=MCPClient)
        client2.disconnect = AsyncMock()
        client2.tools = []

        manager._clients = {"srv1": client1, "srv2": client2}

        await manager.disconnect_all()

        assert len(manager._clients) == 0


class TestMCPToolManagerGetToolSchemas:
    """Tests for getting tool schemas."""

    @pytest.mark.asyncio
    async def test_get_tool_schemas(self, manager):
        """Test getting schemas from all servers."""
        tool1 = create_mock_tool("query", "sqlite")
        tool2 = create_mock_tool("list", "github")

        client1 = MagicMock(spec=MCPClient)
        client1.list_tools = AsyncMock(return_value=[tool1])
        client1.config = MagicMock(cache=True)

        client2 = MagicMock(spec=MCPClient)
        client2.list_tools = AsyncMock(return_value=[tool2])
        client2.config = MagicMock(cache=False)

        manager._clients = {"sqlite": client1, "github": client2}

        schemas = await manager.get_tool_schemas()

        assert len(schemas) == 2
        names = [s["name"] for s in schemas]
        assert "mcp_sqlite_query" in names
        assert "mcp_github_list" in names

    @pytest.mark.asyncio
    async def test_get_tool_schemas_force_refresh(self, manager):
        """Test force refresh fetches fresh schemas."""
        tool = create_mock_tool("query", "sqlite")
        client = MagicMock(spec=MCPClient)
        client.list_tools = AsyncMock(return_value=[tool])
        client.config = MagicMock(cache=True)

        manager._clients = {"sqlite": client}

        await manager.get_tool_schemas(force_refresh=True)

        client.list_tools.assert_called_once_with(force_refresh=True)


class TestMCPToolManagerCallTool:
    """Tests for tool invocation."""

    @pytest.mark.asyncio
    async def test_call_tool_success(self, manager):
        """Test successful tool call."""
        tool = create_mock_tool("query", "sqlite")

        client = MagicMock(spec=MCPClient)
        client.get_tool_by_prefixed_name = MagicMock(return_value=tool)
        client.call_tool = AsyncMock(return_value="result")

        manager._clients = {"sqlite": client}
        manager._tool_to_server = {"mcp_sqlite_query": "sqlite"}

        result = await manager.call_tool("mcp_sqlite_query", {"sql": "SELECT 1"})

        assert result == "result"
        client.call_tool.assert_called_once_with("query", {"sql": "SELECT 1"})

    @pytest.mark.asyncio
    async def test_call_tool_unknown(self, manager):
        """Test error for unknown tool."""
        from silica.developer.mcp.client import MCPToolError

        with pytest.raises(MCPToolError, match="Unknown MCP tool"):
            await manager.call_tool("mcp_unknown_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_server_not_connected(self, manager):
        """Test error when server disconnected."""
        from silica.developer.mcp.client import MCPToolError

        manager._tool_to_server = {"mcp_sqlite_query": "sqlite"}
        # No client for sqlite

        with pytest.raises(MCPToolError, match="not connected"):
            await manager.call_tool("mcp_sqlite_query", {})


class TestMCPToolManagerHelpers:
    """Tests for helper methods."""

    def test_get_server_for_tool(self, manager):
        """Test getting server name for tool."""
        manager._tool_to_server = {"mcp_sqlite_query": "sqlite"}
        assert manager.get_server_for_tool("mcp_sqlite_query") == "sqlite"
        assert manager.get_server_for_tool("unknown") is None

    def test_is_mcp_tool(self, manager):
        """Test checking if tool is MCP tool."""
        manager._tool_to_server = {"mcp_sqlite_query": "sqlite"}
        assert manager.is_mcp_tool("mcp_sqlite_query") is True
        assert manager.is_mcp_tool("regular_tool") is False

    def test_get_connected_server_names(self, manager):
        """Test getting connected server names."""
        client1 = MagicMock()
        client1.is_connected = True
        client2 = MagicMock()
        client2.is_connected = False

        manager._clients = {"srv1": client1, "srv2": client2}

        names = manager.get_connected_server_names()
        assert names == ["srv1"]

    def test_get_all_tools(self, manager):
        """Test getting all tools."""
        tool1 = create_mock_tool("a", "srv1")
        tool2 = create_mock_tool("b", "srv2")

        client1 = MagicMock()
        client1.tools = [tool1]
        client2 = MagicMock()
        client2.tools = [tool2]

        manager._clients = {"srv1": client1, "srv2": client2}

        tools = manager.get_all_tools()
        assert len(tools) == 2


class TestMCPToolManagerCache:
    """Tests for cache management."""

    def test_set_cache_enabled(self, manager):
        """Test setting cache enabled."""
        client = MagicMock()
        client.config = MagicMock(cache=True)
        manager._clients = {"sqlite": client}

        manager.set_cache_enabled("sqlite", False)

        assert client.config.cache is False

    def test_set_cache_unknown_server(self, manager):
        """Test error for unknown server."""
        with pytest.raises(ValueError, match="not connected"):
            manager.set_cache_enabled("unknown", True)

    def test_get_cache_enabled(self, manager):
        """Test getting cache status."""
        client = MagicMock()
        client.config = MagicMock(cache=True)
        manager._clients = {"sqlite": client}

        assert manager.get_cache_enabled("sqlite") is True


class TestMCPToolManagerStatus:
    """Tests for status reporting."""

    def test_get_server_status_no_config(self, manager):
        """Test status with no config."""
        assert manager.get_server_status() == []

    def test_get_server_status(self, manager, config):
        """Test getting server status."""
        manager._config = config

        client = MagicMock()
        client.is_connected = True
        client.tools = [create_mock_tool("query", "sqlite")]
        manager._clients = {"sqlite": client}

        statuses = manager.get_server_status()

        # Should have all configured servers
        assert len(statuses) == 3
        names = [s.name for s in statuses]
        assert "sqlite" in names
        assert "github" in names
        assert "disabled" in names

        # Check connected status
        sqlite_status = next(s for s in statuses if s.name == "sqlite")
        assert sqlite_status.connected is True
        assert sqlite_status.tool_count == 1

        github_status = next(s for s in statuses if s.name == "github")
        assert github_status.connected is False


class TestMCPToolManagerContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self, manager):
        """Test using manager as context manager."""
        client = MagicMock()
        client.disconnect = AsyncMock()
        client.tools = []
        manager._clients = {"test": client}

        async with manager:
            pass

        # Should have disconnected
        assert len(manager._clients) == 0
