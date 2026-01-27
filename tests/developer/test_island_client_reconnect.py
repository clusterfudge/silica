"""Tests for Island client reconnection behavior."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from silica.developer.island_client.client import (
    IslandClient,
    RECONNECT_BASE_DELAY,
    RECONNECT_MAX_DELAY,
    RECONNECT_MAX_ATTEMPTS,
    HEARTBEAT_INTERVAL,
)


class TestReconnectionInfrastructure:
    """Test reconnection state tracking and backoff."""

    def test_initial_state(self):
        """Client starts with reconnection disabled."""
        client = IslandClient()
        assert not client.connected
        assert not client.reconnecting
        assert client._reconnect_attempts == 0
        assert not client._intentional_disconnect

    def test_auto_reconnect_default_enabled(self):
        """Auto reconnect is enabled by default."""
        client = IslandClient()
        assert client.auto_reconnect is True

    def test_auto_reconnect_can_be_disabled(self):
        """Auto reconnect can be disabled."""
        client = IslandClient(auto_reconnect=False)
        assert client.auto_reconnect is False

    @pytest.mark.asyncio
    async def test_intentional_disconnect_prevents_reconnection(self):
        """Calling disconnect() sets intentional flag."""
        client = IslandClient()
        client._connected = True
        client._writer = MagicMock()
        client._writer.close = MagicMock()
        client._writer.wait_closed = AsyncMock()

        await client.disconnect()

        assert client._intentional_disconnect is True
        assert not client.reconnecting

    @pytest.mark.asyncio
    async def test_connection_lost_triggers_reconnection(self):
        """Unintentional connection loss triggers reconnection."""
        client = IslandClient()
        client._connected = True
        client._intentional_disconnect = False
        client.auto_reconnect = True

        # Mock the reconnection loop to just set the flag
        with patch.object(client, "_reconnection_loop", new_callable=AsyncMock):
            await client._handle_connection_lost()

        assert client.reconnecting or client._reconnect_task is not None

    @pytest.mark.asyncio
    async def test_no_reconnection_when_disabled(self):
        """No reconnection when auto_reconnect is False."""
        client = IslandClient(auto_reconnect=False)
        client._connected = True
        client._intentional_disconnect = False

        await client._handle_connection_lost()

        assert not client.reconnecting
        assert client._reconnect_task is None


class TestExponentialBackoff:
    """Test exponential backoff timing."""

    def test_backoff_calculation(self):
        """Verify exponential backoff values."""
        # attempt 0: 0.5 * 2^0 = 0.5
        # attempt 1: 0.5 * 2^1 = 1.0
        # attempt 2: 0.5 * 2^2 = 2.0
        # etc, capped at 16
        expected = [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 16.0]

        for attempt, expected_delay in enumerate(expected):
            delay = min(
                RECONNECT_BASE_DELAY * (2**attempt),
                RECONNECT_MAX_DELAY,
            )
            assert delay == expected_delay

    def test_max_attempts_constant(self):
        """Verify max attempts is reasonable."""
        assert RECONNECT_MAX_ATTEMPTS == 20


class TestSessionReregistration:
    """Test session re-registration on reconnect."""

    @pytest.mark.asyncio
    async def test_session_info_stored_on_register(self):
        """Session info is stored when registering."""
        client = IslandClient()
        client._connected = True
        client._writer = MagicMock()
        client._writer.write = MagicMock()
        client._writer.drain = AsyncMock()

        # Mock the request to succeed
        async def mock_send_request(method, params, **kwargs):
            return {"registered": True}

        with patch.object(client, "_send_request", side_effect=mock_send_request):
            await client.register_session(
                session_id="test-session",
                working_directory="/tmp",
                model="claude-3",
                persona="dev",
            )

        assert client._session_info is not None
        assert client._session_info["session_id"] == "test-session"
        assert client._session_info["working_directory"] == "/tmp"
        assert client._session_info["model"] == "claude-3"

    @pytest.mark.asyncio
    async def test_session_info_cleared_on_unregister(self):
        """Session info is cleared when unregistering."""
        client = IslandClient()
        client._connected = True
        client._session_info = {"session_id": "test"}

        async def mock_send_request(method, params, **kwargs):
            return {}

        with patch.object(client, "_send_request", side_effect=mock_send_request):
            await client.unregister_session("test")

        assert client._session_info is None

    @pytest.mark.asyncio
    async def test_on_reconnected_reregisters_session(self):
        """Session is re-registered after reconnection."""
        client = IslandClient()
        client._connected = True
        client._session_info = {
            "session_id": "test-session",
            "working_directory": "/tmp",
            "model": "claude-3",
            "persona": None,
        }

        register_called = False

        async def mock_register(**kwargs):
            nonlocal register_called
            register_called = True
            assert kwargs["session_id"] == "test-session"
            return True

        with patch.object(client, "register_session", side_effect=mock_register):
            await client._on_reconnected()

        assert register_called


class TestHeartbeat:
    """Test heartbeat/ping mechanism."""

    def test_heartbeat_interval_constant(self):
        """Verify heartbeat interval is reasonable."""
        assert HEARTBEAT_INTERVAL == 30.0

    @pytest.mark.asyncio
    async def test_heartbeat_starts_on_connect(self):
        """Heartbeat task starts after connection."""
        client = IslandClient()

        with patch.object(client, "socket_exists", return_value=True):
            with patch("asyncio.open_unix_connection") as mock_conn:
                mock_reader = MagicMock()
                mock_reader.readline = AsyncMock(return_value=b"")
                mock_writer = MagicMock()
                mock_writer.write = MagicMock()
                mock_writer.drain = AsyncMock()
                mock_writer.close = MagicMock()
                mock_writer.wait_closed = AsyncMock()
                mock_conn.return_value = (mock_reader, mock_writer)

                with patch.object(client, "_handshake", return_value=True):
                    await client.connect()

                    # Heartbeat should be started
                    assert client._heartbeat_task is not None

                    await client.disconnect()

    @pytest.mark.asyncio
    async def test_heartbeat_stops_on_disconnect(self):
        """Heartbeat task stops on intentional disconnect."""
        client = IslandClient()
        client._connected = True
        client._heartbeat_task = asyncio.create_task(asyncio.sleep(100))
        client._writer = MagicMock()
        client._writer.close = MagicMock()
        client._writer.wait_closed = AsyncMock()

        await client.disconnect()

        assert client._heartbeat_task is None


class TestSilentFailure:
    """Test silent failure mode for fire-and-forget operations."""

    @pytest.mark.asyncio
    async def test_notification_silent_when_disconnected(self):
        """Notifications fail silently when not connected."""
        client = IslandClient()
        client._connected = False

        # Should not raise, should not log
        await client.notify_user_message("test")
        await client.notify_assistant_message("test")
        await client.notify_tool_use("test", {})
        await client.notify_status("test")

    @pytest.mark.asyncio
    async def test_notification_silent_on_write_error(self):
        """Notifications fail silently on write errors."""
        client = IslandClient()
        client._connected = True
        client._writer = MagicMock()
        client._writer.write = MagicMock(side_effect=Exception("Write failed"))
        client._writer.drain = AsyncMock()

        # Should not raise
        await client.notify_user_message("test")


class TestReconnectedCallback:
    """Test the on_reconnected callback."""

    @pytest.mark.asyncio
    async def test_callback_called_on_reconnection(self):
        """on_reconnected callback is called after reconnection."""
        client = IslandClient()
        client._connected = True

        callback_called = False

        def on_reconnected():
            nonlocal callback_called
            callback_called = True

        client.on_reconnected = on_reconnected

        await client._on_reconnected()

        assert callback_called

    @pytest.mark.asyncio
    async def test_async_callback_supported(self):
        """Async on_reconnected callbacks work."""
        client = IslandClient()
        client._connected = True

        callback_called = False

        async def on_reconnected():
            nonlocal callback_called
            callback_called = True

        client.on_reconnected = on_reconnected

        await client._on_reconnected()

        assert callback_called

    @pytest.mark.asyncio
    async def test_callback_error_does_not_propagate(self):
        """Errors in on_reconnected callback don't propagate."""
        client = IslandClient()
        client._connected = True

        def on_reconnected():
            raise ValueError("Callback error")

        client.on_reconnected = on_reconnected

        # Should not raise
        await client._on_reconnected()
