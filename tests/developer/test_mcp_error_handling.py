"""Tests for MCP error handling and resilience.

Tests timeout handling, retry logic, server crash detection,
and error translation.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from silica.developer.mcp.client import (
    MCPClient,
    MCPConnectionError,
    MCPServerCrashedError,
    MCPTimeoutError,
    MCPToolError,
)
from silica.developer.mcp.config import MCPServerConfig
from silica.developer.mcp.manager import (
    MCPToolManager,
)


class TestMCPClientTimeout:
    """Tests for MCPClient timeout handling."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock server config."""
        return MCPServerConfig(
            name="test_server",
            command="test_cmd",
            args=["arg1"],
        )

    @pytest.mark.asyncio
    async def test_connect_timeout(self, mock_config):
        """Test that connect raises MCPTimeoutError on timeout."""
        client = MCPClient(config=mock_config)

        with patch("silica.developer.mcp.client.stdio_client") as mock_stdio:
            # Create an async context manager that times out
            class SlowContextManager:
                async def __aenter__(self):
                    await asyncio.sleep(10)  # Will be cancelled by timeout
                    return (MagicMock(), MagicMock())

                async def __aexit__(self, *args):
                    pass

            mock_stdio.return_value = SlowContextManager()

            with pytest.raises(MCPTimeoutError) as exc_info:
                await client.connect(timeout=0.1)

            assert "Timeout" in str(exc_info.value)
            assert "test_server" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_tool_call_timeout(self, mock_config):
        """Test that call_tool raises MCPTimeoutError on timeout."""
        client = MCPClient(config=mock_config)
        client._connected = True
        client._session = MagicMock()

        # Make call_tool hang
        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10)

        client._session.call_tool = slow_call

        with pytest.raises(MCPTimeoutError) as exc_info:
            await client.call_tool("test_tool", {}, timeout=0.1)

        assert "Timeout" in str(exc_info.value)
        assert "test_tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_tools_timeout(self, mock_config):
        """Test that list_tools raises MCPTimeoutError on timeout."""
        client = MCPClient(config=mock_config)
        client._connected = True
        client._session = MagicMock()

        # Make list_tools hang
        async def slow_list():
            await asyncio.sleep(10)

        client._session.list_tools = slow_list

        with pytest.raises(MCPTimeoutError) as exc_info:
            await client.list_tools(timeout=0.1)

        assert "Timeout" in str(exc_info.value)


class TestMCPClientServerCrash:
    """Tests for server crash detection."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock server config."""
        return MCPServerConfig(
            name="test_server",
            command="test_cmd",
            args=["arg1"],
        )

    def test_check_server_crashed_no_streams(self, mock_config):
        """Test crash detection when streams are None."""
        client = MCPClient(config=mock_config)
        client._connected = True
        client._read_stream = None
        client._write_stream = None

        assert client._check_server_crashed() is True

    def test_check_server_crashed_stream_at_eof(self, mock_config):
        """Test crash detection when stream is at EOF."""
        client = MCPClient(config=mock_config)
        client._connected = True
        client._read_stream = MagicMock()
        client._read_stream.at_eof.return_value = True
        client._write_stream = MagicMock()

        assert client._check_server_crashed() is True

    def test_check_server_crashed_healthy(self, mock_config):
        """Test crash detection returns False for healthy connection."""
        client = MCPClient(config=mock_config)
        client._connected = True
        client._read_stream = MagicMock()
        client._read_stream.at_eof.return_value = False
        client._write_stream = MagicMock()

        assert client._check_server_crashed() is False


class TestMCPToolErrorAttributes:
    """Tests for MCPToolError attributes."""

    def test_error_with_tool_name(self):
        """Test MCPToolError includes tool name."""
        error = MCPToolError("Test error", tool_name="my_tool")
        assert error.tool_name == "my_tool"
        assert error.is_error is True

    def test_error_is_error_flag(self):
        """Test MCPToolError is_error flag."""
        error = MCPToolError("Warning", is_error=False)
        assert error.is_error is False

    def test_timeout_error_inherits_from_tool_error(self):
        """Test MCPTimeoutError is a subclass of MCPToolError."""
        assert issubclass(MCPTimeoutError, MCPToolError)

    def test_server_crashed_error_inherits_from_connection_error(self):
        """Test MCPServerCrashedError is a subclass of MCPConnectionError."""
        assert issubclass(MCPServerCrashedError, MCPConnectionError)


class TestMCPManagerRetry:
    """Tests for MCPToolManager retry logic."""

    @pytest.mark.asyncio
    async def test_connect_server_retries_on_failure(self):
        """Test that connect_server retries on transient failures."""
        manager = MCPToolManager()

        # Create mock config
        config = MagicMock()
        config.servers = {
            "test": MCPServerConfig(
                name="test",
                command="cmd",
                args=[],
            )
        }
        manager._config = config

        call_count = 0

        with patch("silica.developer.mcp.manager.MCPClient") as MockClient:

            async def connect_with_failures(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise MCPConnectionError("Transient failure")
                # Success on 3rd attempt

            mock_client = AsyncMock()
            mock_client.connect = connect_with_failures
            mock_client.tools = []
            MockClient.return_value = mock_client

            await manager.connect_server("test", max_retries=3, retry_delay=0.01)

            assert call_count == 3

    @pytest.mark.asyncio
    async def test_connect_server_fails_after_max_retries(self):
        """Test that connect_server fails after exhausting retries."""
        manager = MCPToolManager()

        config = MagicMock()
        config.servers = {"test": MCPServerConfig(name="test", command="cmd", args=[])}
        manager._config = config

        with patch("silica.developer.mcp.manager.MCPClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.connect = AsyncMock(
                side_effect=MCPConnectionError("Always fails")
            )
            MockClient.return_value = mock_client

            with pytest.raises(MCPConnectionError) as exc_info:
                await manager.connect_server("test", max_retries=2, retry_delay=0.01)

            assert "2 attempts" in str(exc_info.value)


class TestMCPManagerAutoReconnect:
    """Tests for auto-reconnect on server crash."""

    @pytest.mark.asyncio
    async def test_call_tool_auto_reconnects_on_crash(self):
        """Test that call_tool auto-reconnects if server crashes."""
        manager = MCPToolManager()

        # Create a proper tool info mock
        mock_tool_info = MagicMock()
        mock_tool_info.name = "mcp_test_tool"
        mock_tool_info.original_name = "tool"

        # Set up initial client - use MagicMock for non-async methods
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.tools = [mock_tool_info]
        mock_client.get_tool_by_prefixed_name.return_value = mock_tool_info

        call_count = 0

        async def call_with_crash(tool_name, args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise MCPServerCrashedError("Server died")
            return "success"

        mock_client.call_tool = call_with_crash

        manager._clients["test"] = mock_client
        manager._tool_to_server["mcp_test_tool"] = "test"

        # Mock connect_server to replace the client
        async def mock_connect_server(name, **kwargs):
            manager._clients[name] = mock_client

        manager.connect_server = mock_connect_server

        result = await manager.call_tool("mcp_test_tool", {}, auto_reconnect=True)

        assert result == "success"
        assert call_count == 2  # Failed once, succeeded after reconnect


class TestMCPManagerErrorFormatting:
    """Tests for error message formatting."""

    def test_format_timeout_error(self):
        """Test formatting timeout error."""
        manager = MCPToolManager()
        error = MCPTimeoutError("Timed out")
        result = manager.format_error_as_tool_result(error, "my_tool")

        assert "timed out" in result.lower()
        assert "my_tool" in result

    def test_format_crash_error(self):
        """Test formatting server crash error."""
        manager = MCPToolManager()
        error = MCPServerCrashedError("Server crashed")
        result = manager.format_error_as_tool_result(error, "my_tool")

        assert "crashed" in result.lower()
        assert "my_tool" in result

    def test_format_connection_error(self):
        """Test formatting connection error."""
        manager = MCPToolManager()
        error = MCPConnectionError("Cannot connect")
        result = manager.format_error_as_tool_result(error, "my_tool")

        assert "connect" in result.lower() or "unavailable" in result.lower()
        assert "my_tool" in result

    def test_format_tool_error(self):
        """Test formatting generic tool error."""
        manager = MCPToolManager()
        error = MCPToolError("Something went wrong")
        result = manager.format_error_as_tool_result(error, "my_tool")

        assert "Something went wrong" in result


class TestMCPManagerHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_healthy_server(self):
        """Test health check for healthy server."""
        manager = MCPToolManager()

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])
        manager._clients["test"] = mock_client

        results = await manager.health_check()

        assert results["test"] is True
        mock_client.list_tools.assert_called_once_with(force_refresh=True)

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_server(self):
        """Test health check for unhealthy server."""
        manager = MCPToolManager()

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(side_effect=Exception("Server error"))
        manager._clients["test"] = mock_client

        results = await manager.health_check()

        assert results["test"] is False

    @pytest.mark.asyncio
    async def test_health_check_multiple_servers(self):
        """Test health check with multiple servers."""
        manager = MCPToolManager()

        healthy_client = AsyncMock()
        healthy_client.list_tools = AsyncMock(return_value=[])

        unhealthy_client = AsyncMock()
        unhealthy_client.list_tools = AsyncMock(side_effect=Exception("Error"))

        manager._clients["healthy"] = healthy_client
        manager._clients["unhealthy"] = unhealthy_client

        results = await manager.health_check()

        assert results["healthy"] is True
        assert results["unhealthy"] is False
