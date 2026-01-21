"""Tests for HybridUserInterface."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from silica.developer.hybrid_interface import HybridUserInterface
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

    def handle_tool_use(self, tool_name: str, tool_params: dict) -> None:
        self.messages.append(("tool_use", tool_name, tool_params))

    def handle_tool_result(self, name: str, result: dict, live=None) -> None:
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

        # Check Island was notified
        mock_island.notify_assistant_message.assert_called_once_with(
            content="Hello from assistant", format="markdown"
        )

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
        mock_island.register_session.assert_called_once_with(
            session_id="test-123",
            working_directory="/tmp/test",
            model="claude-sonnet",
            persona="default",
        )

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
