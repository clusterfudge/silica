"""Tests for MCP agent management tools."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from silica.developer.tools.mcp_tools import (
    mcp_list_servers,
    mcp_connect,
    mcp_disconnect,
    mcp_set_cache,
    mcp_refresh,
    mcp_list_tools,
    mcp_auth,
    mcp_auth_revoke,
    mcp_auth_status,
)


@pytest.fixture
def mock_context():
    """Create a mock context with MCP manager."""
    context = MagicMock()
    context.toolbox = MagicMock()
    context.toolbox.mcp_manager = MagicMock()
    return context


@pytest.fixture
def mock_context_no_mcp():
    """Create a mock context without MCP manager."""
    context = MagicMock()
    context.toolbox = None
    return context


class TestMcpListServers:
    """Tests for mcp_list_servers tool."""

    @pytest.mark.asyncio
    async def test_no_mcp_configured(self, mock_context_no_mcp):
        """Test when MCP is not configured."""
        result = await mcp_list_servers(mock_context_no_mcp)
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_no_servers(self, mock_context):
        """Test with no servers configured."""
        mock_context.toolbox.mcp_manager.get_server_status.return_value = []
        result = await mcp_list_servers(mock_context)
        assert "No MCP servers configured" in result

    @pytest.mark.asyncio
    async def test_list_servers(self, mock_context):
        """Test listing servers with status."""
        from silica.developer.mcp import ServerStatus

        statuses = [
            ServerStatus(
                name="sqlite",
                connected=True,
                tool_count=5,
                cache_enabled=True,
            ),
            ServerStatus(
                name="github",
                connected=False,
                tool_count=0,
                cache_enabled=False,
            ),
        ]
        mock_context.toolbox.mcp_manager.get_server_status.return_value = statuses
        result = await mcp_list_servers(mock_context)

        assert "sqlite" in result
        assert "connected" in result
        assert "github" in result
        assert "disconnected" in result


class TestMcpConnect:
    """Tests for mcp_connect tool."""

    @pytest.mark.asyncio
    async def test_no_mcp_configured(self, mock_context_no_mcp):
        """Test when MCP is not configured."""
        result = await mcp_connect(mock_context_no_mcp, "test")
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_connect_success(self, mock_context):
        """Test successful connection."""
        mock_context.toolbox.mcp_manager.connect_server = AsyncMock()
        mock_client = MagicMock()
        mock_client.tools = [MagicMock(), MagicMock()]
        mock_context.toolbox.mcp_manager._clients = {"sqlite": mock_client}

        result = await mcp_connect(mock_context, "sqlite")

        assert "Connected" in result
        assert "sqlite" in result
        assert "2 tools" in result

    @pytest.mark.asyncio
    async def test_connect_error(self, mock_context):
        """Test connection failure."""
        mock_context.toolbox.mcp_manager.connect_server = AsyncMock(
            side_effect=ValueError("Server not found")
        )

        result = await mcp_connect(mock_context, "unknown")

        assert "Error" in result or "not found" in result


class TestMcpDisconnect:
    """Tests for mcp_disconnect tool."""

    @pytest.mark.asyncio
    async def test_no_mcp_configured(self, mock_context_no_mcp):
        """Test when MCP is not configured."""
        result = await mcp_disconnect(mock_context_no_mcp, "test")
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_disconnect_success(self, mock_context):
        """Test successful disconnection."""
        mock_context.toolbox.mcp_manager._clients = {"sqlite": MagicMock()}
        mock_context.toolbox.mcp_manager.disconnect_server = AsyncMock()

        result = await mcp_disconnect(mock_context, "sqlite")

        assert "Disconnected" in result
        assert "sqlite" in result

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self, mock_context):
        """Test disconnecting server that isn't connected."""
        mock_context.toolbox.mcp_manager._clients = {}

        result = await mcp_disconnect(mock_context, "unknown")

        assert "not connected" in result.lower()


class TestMcpSetCache:
    """Tests for mcp_set_cache tool."""

    @pytest.mark.asyncio
    async def test_no_mcp_configured(self, mock_context_no_mcp):
        """Test when MCP is not configured."""
        result = await mcp_set_cache(mock_context_no_mcp, "test", True)
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_set_cache_enabled(self, mock_context):
        """Test enabling cache."""
        result = await mcp_set_cache(mock_context, "sqlite", True)

        assert "enabled" in result.lower()
        mock_context.toolbox.mcp_manager.set_cache_enabled.assert_called_once_with(
            "sqlite", True
        )

    @pytest.mark.asyncio
    async def test_set_cache_disabled(self, mock_context):
        """Test disabling cache."""
        result = await mcp_set_cache(mock_context, "sqlite", False)

        assert "disabled" in result.lower()
        mock_context.toolbox.mcp_manager.set_cache_enabled.assert_called_once_with(
            "sqlite", False
        )


class TestMcpRefresh:
    """Tests for mcp_refresh tool."""

    @pytest.mark.asyncio
    async def test_no_mcp_configured(self, mock_context_no_mcp):
        """Test when MCP is not configured."""
        result = await mcp_refresh(mock_context_no_mcp)
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_refresh_specific_server(self, mock_context):
        """Test refreshing specific server."""
        mock_context.toolbox.mcp_manager.refresh_schemas = AsyncMock()
        mock_client = MagicMock()
        mock_client.tools = [MagicMock(), MagicMock(), MagicMock()]
        mock_context.toolbox.mcp_manager._clients = {"sqlite": mock_client}

        result = await mcp_refresh(mock_context, "sqlite")

        assert "Refreshed" in result
        assert "sqlite" in result

    @pytest.mark.asyncio
    async def test_refresh_all_servers(self, mock_context):
        """Test refreshing all servers."""
        mock_context.toolbox.mcp_manager.refresh_schemas = AsyncMock()
        mock_client = MagicMock()
        mock_client.tools = [MagicMock()]
        mock_context.toolbox.mcp_manager._clients = {
            "srv1": mock_client,
            "srv2": mock_client,
        }

        result = await mcp_refresh(mock_context)

        assert "Refreshed" in result
        assert "all servers" in result.lower()


class TestMcpListTools:
    """Tests for mcp_list_tools tool."""

    @pytest.mark.asyncio
    async def test_no_mcp_configured(self, mock_context_no_mcp):
        """Test when MCP is not configured."""
        result = await mcp_list_tools(mock_context_no_mcp)
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_no_tools(self, mock_context):
        """Test with no tools available."""
        mock_context.toolbox.mcp_manager.get_all_tools.return_value = []

        result = await mcp_list_tools(mock_context)

        assert "No MCP tools available" in result

    @pytest.mark.asyncio
    async def test_list_tools(self, mock_context):
        """Test listing tools from servers."""
        from silica.developer.mcp import MCPToolInfo

        tools = [
            MCPToolInfo(
                name="mcp_sqlite_query",
                description="Run a SQL query",
                input_schema={},
                server_name="sqlite",
                original_name="query",
            ),
            MCPToolInfo(
                name="mcp_sqlite_insert",
                description="Insert data",
                input_schema={},
                server_name="sqlite",
                original_name="insert",
            ),
        ]
        mock_context.toolbox.mcp_manager.get_all_tools.return_value = tools

        result = await mcp_list_tools(mock_context)

        assert "sqlite" in result
        assert "mcp_sqlite_query" in result
        assert "Run a SQL query" in result

    @pytest.mark.asyncio
    async def test_list_tools_filtered(self, mock_context):
        """Test listing tools filtered by server."""
        from silica.developer.mcp import MCPToolInfo

        tools = [
            MCPToolInfo(
                name="mcp_sqlite_query",
                description="Query",
                input_schema={},
                server_name="sqlite",
                original_name="query",
            ),
            MCPToolInfo(
                name="mcp_github_list",
                description="List",
                input_schema={},
                server_name="github",
                original_name="list",
            ),
        ]
        mock_context.toolbox.mcp_manager.get_all_tools.return_value = tools

        result = await mcp_list_tools(mock_context, "sqlite")

        assert "sqlite" in result
        assert "github" not in result


class TestMcpAuth:
    """Tests for mcp_auth tool."""

    @pytest.mark.asyncio
    async def test_no_mcp_configured(self, mock_context_no_mcp):
        """Test when MCP is not configured."""
        result = await mcp_auth(mock_context_no_mcp, "test")
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_no_config(self, mock_context):
        """Test when no config loaded."""
        mock_context.toolbox.mcp_manager._config = None

        result = await mcp_auth(mock_context, "test")
        assert "No MCP configuration" in result

    @pytest.mark.asyncio
    async def test_server_not_found(self, mock_context):
        """Test when server not found."""
        mock_context.toolbox.mcp_manager._config = MagicMock()
        mock_context.toolbox.mcp_manager._config.servers = {}

        result = await mcp_auth(mock_context, "unknown")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_server_no_auth_required(self, mock_context):
        """Test when server doesn't require auth."""
        mock_context.toolbox.mcp_manager._config = MagicMock()
        mock_server = MagicMock()
        mock_server.auth = None
        mock_context.toolbox.mcp_manager._config.servers = {"sqlite": mock_server}

        result = await mcp_auth(mock_context, "sqlite")
        assert "does not require authentication" in result


class TestMcpAuthRevoke:
    """Tests for mcp_auth_revoke tool."""

    @pytest.mark.asyncio
    async def test_no_mcp_configured(self, mock_context_no_mcp):
        """Test when MCP is not configured."""
        result = await mcp_auth_revoke(mock_context_no_mcp, "test")
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_no_config(self, mock_context):
        """Test when no config loaded."""
        mock_context.toolbox.mcp_manager._config = None

        result = await mcp_auth_revoke(mock_context, "test")
        assert "No MCP configuration" in result

    @pytest.mark.asyncio
    async def test_server_not_found(self, mock_context):
        """Test when server not found."""
        mock_context.toolbox.mcp_manager._config = MagicMock()
        mock_context.toolbox.mcp_manager._config.servers = {}

        result = await mcp_auth_revoke(mock_context, "unknown")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_server_no_auth_config(self, mock_context):
        """Test when server doesn't have auth configured."""
        mock_context.toolbox.mcp_manager._config = MagicMock()
        mock_server = MagicMock()
        mock_server.auth = None
        mock_context.toolbox.mcp_manager._config.servers = {"sqlite": mock_server}

        result = await mcp_auth_revoke(mock_context, "sqlite")
        assert "does not have authentication configured" in result


class TestMcpAuthStatus:
    """Tests for mcp_auth_status tool."""

    @pytest.mark.asyncio
    async def test_no_mcp_configured(self, mock_context_no_mcp):
        """Test when MCP is not configured."""
        result = await mcp_auth_status(mock_context_no_mcp)
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_no_config(self, mock_context):
        """Test when no config loaded."""
        mock_context.toolbox.mcp_manager._config = None

        result = await mcp_auth_status(mock_context)
        assert "No MCP configuration" in result

    @pytest.mark.asyncio
    async def test_no_servers_with_auth(self, mock_context):
        """Test when no servers have auth config."""
        mock_context.toolbox.mcp_manager._config = MagicMock()
        mock_server = MagicMock()
        mock_server.auth = None
        mock_context.toolbox.mcp_manager._config.servers = {"sqlite": mock_server}

        result = await mcp_auth_status(mock_context)
        assert "No MCP servers with authentication" in result
