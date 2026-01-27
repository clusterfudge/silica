"""Tests for HybridUserInterface."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from silica.developer.hybrid_interface import (
    HybridUserInterface,
    _fire_and_forget,
    _strip_rich_markup,
)
from silica.developer.sandbox import SandboxMode


class MockCLIInterface:
    """Mock CLI interface for testing."""

    def __init__(self):
        self.messages = []
        self.permission_response = True

    def handle_assistant_message(self, message: str) -> None:
        self.messages.append(("assistant", message))

    def handle_system_message(self, message: str, markdown=True, live=None) -> None:
        self.messages.append(("system", message))

    def handle_tool_use(
        self, tool_name: str, tool_params: dict, tool_use_id=None
    ) -> None:
        self.messages.append(("tool_use", tool_name, tool_params))

    def handle_tool_result(
        self, name: str, result: dict, live=None, tool_use_id=None
    ) -> None:
        self.messages.append(("tool_result", name, result))

    def handle_user_input(self, user_input: str) -> str:
        return user_input

    def permission_callback(self, action, resource, mode, args, group=None):
        return self.permission_response

    def permission_rendering_callback(self, action, resource, args):
        pass

    async def get_user_input(self, prompt: str = "") -> str:
        return "test input"

    async def get_user_choice(self, question: str, options: list) -> str:
        return options[0] if options else "test"

    async def get_session_choice(self, sessions: list) -> str | None:
        return sessions[0]["session_id"] if sessions else None

    async def run_questionnaire(self, title: str, questions: list) -> dict | None:
        return {q.id: "answer" for q in questions}

    def display_token_count(self, *args, **kwargs) -> None:
        self.messages.append(("token_count", kwargs))

    def display_welcome_message(self) -> None:
        self.messages.append(("welcome",))

    def status(self, message: str, spinner: str = None):
        return MagicMock(__enter__=MagicMock(), __exit__=MagicMock())

    def bare(self, message, live=None) -> None:
        self.messages.append(("bare", message))


class TestHybridInterfaceWithoutIsland:
    """Test HybridUserInterface when Agent Island is not available."""

    def test_not_hybrid_when_socket_missing(self, tmp_path):
        """Should not be in hybrid mode when socket doesn't exist."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "nonexistent.sock")

        assert not hybrid.hybrid_mode

    def test_permission_callback_uses_cli(self, tmp_path):
        """Permission callback should use CLI when Island not available."""
        cli = MockCLIInterface()
        cli.permission_response = True
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "nonexistent.sock")

        result = hybrid.permission_callback(
            "read_file", "test.py", SandboxMode.REQUEST_EVERY_TIME, None
        )

        assert result is True

    def test_events_go_to_cli_only(self, tmp_path):
        """Events should go to CLI when Island not available."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "nonexistent.sock")

        hybrid.handle_assistant_message("Hello")
        hybrid.handle_system_message("System message")
        hybrid.handle_tool_use("test_tool", {"param": "value"})
        hybrid.handle_tool_result("test_tool", {"result": "ok"})

        assert len(cli.messages) == 4
        assert cli.messages[0] == ("assistant", "Hello")
        assert cli.messages[1] == ("system", "System message")

    @pytest.mark.asyncio
    async def test_get_user_input_uses_cli(self, tmp_path):
        """get_user_input should use CLI."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "nonexistent.sock")

        result = await hybrid.get_user_input("prompt> ")
        assert result == "test input"

    @pytest.mark.asyncio
    async def test_get_user_choice_uses_cli(self, tmp_path):
        """get_user_choice should use CLI when Island not available."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "nonexistent.sock")

        result = await hybrid.get_user_choice("Pick one:", ["A", "B", "C"])
        assert result == "A"


class TestHybridInterfaceConnectionHandling:
    """Test connection handling logic."""

    @pytest.mark.asyncio
    async def test_connect_fails_gracefully_when_socket_missing(self, tmp_path):
        """connect_to_island should return False when socket doesn't exist."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "nonexistent.sock")

        connected = await hybrid.connect_to_island()
        assert connected is False
        assert not hybrid.hybrid_mode

    @pytest.mark.asyncio
    async def test_connect_caches_unavailable_status(self, tmp_path):
        """Should cache that Island is unavailable after first check."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "nonexistent.sock")

        # First attempt
        await hybrid.connect_to_island()
        assert hybrid._island_available is False

        # Second attempt should return immediately
        connected = await hybrid.connect_to_island()
        assert connected is False


class TestHybridInterfaceWithMockedIsland:
    """Test HybridUserInterface with a mocked Island client."""

    @pytest.mark.asyncio
    async def test_events_sent_to_both_when_connected(self, tmp_path):
        """Events should be sent to both CLI and Island when connected."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "test.sock")

        # Mock the Island client
        mock_island = MagicMock()
        mock_island.connected = True
        mock_island.notify_assistant_message = AsyncMock()
        mock_island.notify_system_message = AsyncMock()
        mock_island.notify_tool_use = AsyncMock()
        mock_island.notify_tool_result = AsyncMock()

        hybrid._island = mock_island
        hybrid._island_available = True

        # Send events
        hybrid.handle_assistant_message("Hello from assistant")

        # Give async tasks a chance to run
        await asyncio.sleep(0.1)

        # Check CLI received the message
        assert ("assistant", "Hello from assistant") in cli.messages

        # Check Island was notified (message_id is dynamically generated)
        mock_island.notify_assistant_message.assert_called_once()
        call_kwargs = mock_island.notify_assistant_message.call_args.kwargs
        assert call_kwargs["content"] == "Hello from assistant"
        assert call_kwargs["format"] == "markdown"

    @pytest.mark.asyncio
    async def test_token_usage_sent_to_both(self, tmp_path):
        """Token usage should be sent to both CLI and Island."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "test.sock")

        mock_island = MagicMock()
        mock_island.connected = True
        mock_island.notify_token_usage = AsyncMock()

        hybrid._island = mock_island
        hybrid._island_available = True

        hybrid.display_token_count(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            total_cost=0.01,
        )

        await asyncio.sleep(0.1)

        # Check CLI received it
        assert any(msg[0] == "token_count" for msg in cli.messages)

        # Check Island was notified
        mock_island.notify_token_usage.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_session(self, tmp_path):
        """Should register session with Island when connected."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "test.sock")

        mock_island = MagicMock()
        mock_island.connected = True
        mock_island.register_session = AsyncMock(return_value=True)

        hybrid._island = mock_island
        hybrid._island_available = True

        result = await hybrid.register_session(
            session_id="test-123",
            working_directory="/tmp/test",
            model="claude-sonnet",
            persona="default",
        )

        assert result is True
        mock_island.register_session.assert_called_once()
        call_kwargs = mock_island.register_session.call_args.kwargs
        assert call_kwargs["session_id"] == "test-123"
        assert call_kwargs["working_directory"] == "/tmp/test"
        assert call_kwargs["model"] == "claude-sonnet"
        assert call_kwargs["persona"] == "default"

    @pytest.mark.asyncio
    async def test_register_session_when_not_connected(self, tmp_path):
        """Should return True even when Island not connected."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "nonexistent.sock")

        result = await hybrid.register_session(
            session_id="test-123", working_directory="/tmp/test"
        )

        # Should succeed silently when Island not available
        assert result is True


class TestFireAndForget:
    """Test the _fire_and_forget helper function."""

    @pytest.mark.asyncio
    async def test_fire_and_forget_with_event_loop(self):
        """_fire_and_forget should schedule coroutine when loop is running."""
        executed = []

        async def test_coro():
            executed.append(True)

        _fire_and_forget(test_coro())

        # Give the task a chance to run
        await asyncio.sleep(0.1)

        assert executed == [True]

    def test_fire_and_forget_without_event_loop(self):
        """_fire_and_forget should not raise when no event loop is running."""
        executed = []

        async def test_coro():
            executed.append(True)

        # This should NOT raise, even though there's no event loop
        _fire_and_forget(test_coro())

        # The coroutine should NOT have executed
        assert executed == []

    def test_fire_and_forget_closes_coroutine(self):
        """_fire_and_forget should close the coroutine to avoid warnings."""

        # Create a coroutine
        async def test_coro():
            pass

        coro = test_coro()

        # This should close the coroutine without warnings
        _fire_and_forget(coro)

        # Verify the coroutine was closed by checking it raises RuntimeError
        # when we try to send to it (closed/awaited coroutines raise this)
        with pytest.raises(
            RuntimeError, match="cannot reuse already awaited coroutine"
        ):
            coro.send(None)


class TestHybridInterfaceNoEventLoop:
    """Test HybridUserInterface methods called without an event loop."""

    def test_handle_system_message_without_event_loop(self, tmp_path):
        """handle_system_message should not raise when no event loop is running."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "test.sock")

        # Mock the Island client as connected
        mock_island = MagicMock()
        mock_island.connected = True
        mock_island.notify_system_message = AsyncMock()

        hybrid._island = mock_island
        hybrid._island_available = True

        # This should NOT raise "no running event loop" error
        hybrid.handle_system_message("Test message")

        # CLI should still have received the message
        assert ("system", "Test message") in cli.messages

    def test_handle_assistant_message_without_event_loop(self, tmp_path):
        """handle_assistant_message should not raise when no event loop is running."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "test.sock")

        mock_island = MagicMock()
        mock_island.connected = True
        mock_island.notify_assistant_message = AsyncMock()

        hybrid._island = mock_island
        hybrid._island_available = True

        # This should NOT raise
        hybrid.handle_assistant_message("Hello")

        assert ("assistant", "Hello") in cli.messages

    def test_handle_tool_use_without_event_loop(self, tmp_path):
        """handle_tool_use should not raise when no event loop is running."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "test.sock")

        mock_island = MagicMock()
        mock_island.connected = True
        mock_island.notify_tool_use = AsyncMock()

        hybrid._island = mock_island
        hybrid._island_available = True

        # This should NOT raise
        hybrid.handle_tool_use("test_tool", {"param": "value"})

        assert ("tool_use", "test_tool", {"param": "value"}) in cli.messages


class TestStripRichMarkup:
    """Test Rich markup stripping for Island."""

    def test_strip_simple_tags(self):
        """Should strip simple Rich tags."""
        assert _strip_rich_markup("[bold]Hello[/bold]") == "Hello"
        assert _strip_rich_markup("[blue]World[/blue]") == "World"
        assert _strip_rich_markup("[dim]text[/dim]") == "text"

    def test_strip_compound_tags(self):
        """Should strip compound Rich tags."""
        assert _strip_rich_markup("[bold blue]Hello[/bold blue]") == "Hello"
        assert _strip_rich_markup("[bold red]Error[/bold red]") == "Error"

    def test_strip_nested_tags(self):
        """Should strip nested Rich tags."""
        text = "[bold][blue]You:[/blue][/bold] Hello"
        assert _strip_rich_markup(text) == "You: Hello"

    def test_preserve_non_markup_brackets(self):
        """Should preserve brackets that aren't Rich markup."""
        # Array indexing should be preserved
        assert _strip_rich_markup("array[0]") == "array[0]"
        assert _strip_rich_markup("dict['key']") == "dict['key']"
        # Random bracketed text should be preserved
        assert _strip_rich_markup("[some text]") == "[some text]"
        assert _strip_rich_markup("See [this link]") == "See [this link]"

    def test_strip_color_codes(self):
        """Should strip color codes including hex."""
        assert _strip_rich_markup("[#ff0000]Red[/#ff0000]") == "Red"

    def test_empty_string(self):
        """Should handle empty strings."""
        assert _strip_rich_markup("") == ""

    def test_no_markup(self):
        """Should return unchanged if no markup."""
        assert _strip_rich_markup("Hello World") == "Hello World"

    def test_mixed_content(self):
        """Should strip Rich markup but preserve other brackets."""
        text = "[bold]Status:[/bold] array[0] is [green]OK[/green]"
        assert _strip_rich_markup(text) == "Status: array[0] is OK"


class TestIslandInputEchoSuppression:
    """Test that input from Island is not echoed back."""

    @pytest.mark.asyncio
    async def test_input_from_island_not_echoed_back(self, tmp_path):
        """Input received from Island should not be sent back via notify_user_message."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "test.sock")

        mock_island = MagicMock()
        mock_island.connected = True
        mock_island.notify_user_message = AsyncMock()

        hybrid._island = mock_island
        hybrid._island_available = True

        # Simulate input coming from Island
        hybrid._last_input_from_island = True

        # Handle the user input (which would normally echo to Island)
        hybrid.handle_user_input("[bold blue]You:[/bold blue] Hello from Island")

        # Give async tasks a chance to run
        await asyncio.sleep(0.1)

        # Island should NOT have been notified (input came from there)
        mock_island.notify_user_message.assert_not_called()

        # Flag should be reset
        assert not hybrid._last_input_from_island

    @pytest.mark.asyncio
    async def test_input_from_cli_is_sent_to_island(self, tmp_path):
        """Input from CLI should be sent to Island."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "test.sock")

        mock_island = MagicMock()
        mock_island.connected = True
        mock_island.notify_user_message = AsyncMock()

        hybrid._island = mock_island
        hybrid._island_available = True

        # Input from CLI (default)
        hybrid._last_input_from_island = False

        hybrid.handle_user_input("[bold blue]You:[/bold blue] Hello from CLI")

        await asyncio.sleep(0.1)

        # Island SHOULD have been notified
        mock_island.notify_user_message.assert_called_once()

        # Check that Rich markup was stripped
        call_kwargs = mock_island.notify_user_message.call_args.kwargs
        assert call_kwargs["content"] == "You: Hello from CLI"

    @pytest.mark.asyncio
    async def test_system_message_strips_rich_markup(self, tmp_path):
        """System messages should have Rich markup stripped before sending to Island."""
        cli = MockCLIInterface()
        hybrid = HybridUserInterface(cli, socket_path=tmp_path / "test.sock")

        mock_island = MagicMock()
        mock_island.connected = True
        mock_island.notify_system_message = AsyncMock()

        hybrid._island = mock_island
        hybrid._island_available = True

        hybrid.handle_system_message("[dim]✓ Responded in terminal[/dim]")

        await asyncio.sleep(0.1)

        mock_island.notify_system_message.assert_called_once()
        call_kwargs = mock_island.notify_system_message.call_args.kwargs
        assert call_kwargs["message"] == "✓ Responded in terminal"
