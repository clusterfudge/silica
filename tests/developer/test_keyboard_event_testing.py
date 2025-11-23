"""Tests for keyboard event testing documentation and approach.

This test file verifies the keyboard action support added to browser_session_interact.
It demonstrates the solutions to the keyboard event "untrusted" problem.

See docs/developer/keyboard_event_testing.md for full documentation.

Test Strategy:
- These tests verify the action type is recognized and doesn't cause errors
- Full integration tests with real Playwright should be added separately
"""

import json
import pytest
from unittest.mock import Mock, AsyncMock, patch

from silica.developer.tools.browser_session import (
    BrowserSession,
    get_browser_session_manager,
)
from silica.developer.tools.browser_session_tools import (
    browser_session_create,
    browser_session_navigate,
    browser_session_interact,
)
from silica.developer.context import AgentContext


@pytest.fixture
def mock_context():
    """Create a mock AgentContext."""
    return Mock(spec=AgentContext)


@pytest.fixture(autouse=True)
async def cleanup_sessions():
    """Cleanup browser sessions between tests."""
    yield
    manager = get_browser_session_manager()
    for session_name in list(manager.sessions.keys()):
        try:
            await manager.destroy_session(session_name)
        except Exception:
            pass
    manager.sessions.clear()


@pytest.fixture
def mock_playwright():
    """Create mock Playwright with keyboard support."""
    # Create mock keyboard
    mock_keyboard = AsyncMock()
    mock_keyboard.press = AsyncMock()
    mock_keyboard.type = AsyncMock()
    mock_keyboard.down = AsyncMock()
    mock_keyboard.up = AsyncMock()
    mock_keyboard.insert_text = AsyncMock()

    # Create mock page with keyboard
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.click = AsyncMock()
    mock_page.fill = AsyncMock()
    mock_page.select_option = AsyncMock()
    mock_page.hover = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_page.locator = Mock()
    mock_page.title = AsyncMock(return_value="Test Page")
    mock_page.url = AsyncMock(return_value="http://localhost:8000")
    mock_page.evaluate = AsyncMock(return_value={"result": "success"})
    mock_page.keyboard = mock_keyboard
    mock_page.close = AsyncMock()

    # Create mock context
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    # Create mock browser
    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    # Create mock playwright
    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.stop = AsyncMock()

    return mock_pw, mock_keyboard, mock_page


class TestKeyboardActionSupport:
    """Tests that keyboard action types are properly recognized and handled."""

    @pytest.mark.asyncio
    async def test_keyboard_press_action(self, mock_context, mock_playwright):
        """Test that keyboard press action is recognized."""
        mock_pw, mock_keyboard, mock_page = mock_playwright

        with patch(
            "silica.developer.tools.browser_session_tools._check_playwright_available",
            return_value=(True, None),
        ):
            with patch(
                "silica.developer.tools.browser_session.async_playwright",
                return_value=mock_pw,
            ):
                manager = get_browser_session_manager()
                manager.sessions.clear()

                await browser_session_create(mock_context, "test")
                
                # Manually set the keyboard on the session's page
                session = manager.get_session("test")
                session.page.keyboard = mock_keyboard

                # Test keyboard press action
                actions = json.dumps([
                    {"type": "keyboard", "action": "press", "key": "Enter"}
                ])

                result = await browser_session_interact(mock_context, "test", actions)

                # Verify action was recognized and reported
                assert "Pressed key 'Enter'" in result
                assert "ERROR" not in result

    @pytest.mark.asyncio
    async def test_keyboard_type_action(self, mock_context, mock_playwright):
        """Test that keyboard type action is recognized."""
        mock_pw, mock_keyboard, mock_page = mock_playwright

        with patch(
            "silica.developer.tools.browser_session_tools._check_playwright_available",
            return_value=(True, None),
        ):
            with patch(
                "silica.developer.tools.browser_session.async_playwright",
                return_value=mock_pw,
            ):
                manager = get_browser_session_manager()
                manager.sessions.clear()

                await browser_session_create(mock_context, "test")
                session = manager.get_session("test")
                session.page.keyboard = mock_keyboard

                actions = json.dumps([
                    {"type": "keyboard", "action": "type", "text": "hello"}
                ])

                result = await browser_session_interact(mock_context, "test", actions)

                assert "Typed 'hello'" in result
                assert "ERROR" not in result

    @pytest.mark.asyncio
    async def test_keyboard_modifier_combinations(self, mock_context, mock_playwright):
        """Test keyboard actions with modifier key combinations."""
        mock_pw, mock_keyboard, mock_page = mock_playwright

        with patch(
            "silica.developer.tools.browser_session_tools._check_playwright_available",
            return_value=(True, None),
        ):
            with patch(
                "silica.developer.tools.browser_session.async_playwright",
                return_value=mock_pw,
            ):
                manager = get_browser_session_manager()
                manager.sessions.clear()

                await browser_session_create(mock_context, "test")
                session = manager.get_session("test")
                session.page.keyboard = mock_keyboard

                test_combinations = [
                    "Control+K",
                    "Meta+P",
                    "Control+Shift+P",
                    "Alt+F4"
                ]

                for combo in test_combinations:
                    actions = json.dumps([
                        {"type": "keyboard", "action": "press", "key": combo}
                    ])

                    result = await browser_session_interact(mock_context, "test", actions)

                    assert f"Pressed key '{combo}'" in result
                    assert "ERROR" not in result

    @pytest.mark.asyncio
    async def test_keyboard_down_up_actions(self, mock_context, mock_playwright):
        """Test keyboard down and up actions for holding keys."""
        mock_pw, mock_keyboard, mock_page = mock_playwright

        with patch(
            "silica.developer.tools.browser_session_tools._check_playwright_available",
            return_value=(True, None),
        ):
            with patch(
                "silica.developer.tools.browser_session.async_playwright",
                return_value=mock_pw,
            ):
                manager = get_browser_session_manager()
                manager.sessions.clear()

                await browser_session_create(mock_context, "test")
                session = manager.get_session("test")
                session.page.keyboard = mock_keyboard

                actions = json.dumps([
                    {"type": "keyboard", "action": "down", "key": "Shift"},
                    {"type": "keyboard", "action": "press", "key": "A"},
                    {"type": "keyboard", "action": "up", "key": "Shift"}
                ])

                result = await browser_session_interact(mock_context, "test", actions)

                assert "Key down 'Shift'" in result
                assert "Pressed key 'A'" in result
                assert "Key up 'Shift'" in result
                assert "ERROR" not in result

    @pytest.mark.asyncio
    async def test_keyboard_insert_text_action(self, mock_context, mock_playwright):
        """Test keyboard insertText action."""
        mock_pw, mock_keyboard, mock_page = mock_playwright

        with patch(
            "silica.developer.tools.browser_session_tools._check_playwright_available",
            return_value=(True, None),
        ):
            with patch(
                "silica.developer.tools.browser_session.async_playwright",
                return_value=mock_pw,
            ):
                manager = get_browser_session_manager()
                manager.sessions.clear()

                await browser_session_create(mock_context, "test")
                session = manager.get_session("test")
                session.page.keyboard = mock_keyboard

                actions = json.dumps([
                    {"type": "keyboard", "action": "insertText", "text": "pasted"}
                ])

                result = await browser_session_interact(mock_context, "test", actions)

                assert "Inserted text 'pasted'" in result
                assert "ERROR" not in result

    @pytest.mark.asyncio
    async def test_keyboard_action_error_handling(self, mock_context, mock_playwright):
        """Test error handling for keyboard actions with missing parameters."""
        mock_pw, mock_keyboard, mock_page = mock_playwright

        with patch(
            "silica.developer.tools.browser_session_tools._check_playwright_available",
            return_value=(True, None),
        ):
            with patch(
                "silica.developer.tools.browser_session.async_playwright",
                return_value=mock_pw,
            ):
                manager = get_browser_session_manager()
                manager.sessions.clear()

                await browser_session_create(mock_context, "test")
                session = manager.get_session("test")
                session.page.keyboard = mock_keyboard

                # Test missing 'key' for press
                actions = json.dumps([{"type": "keyboard", "action": "press"}])
                result = await browser_session_interact(mock_context, "test", actions)
                assert "missing 'key'" in result

                # Test missing 'text' for type
                actions = json.dumps([{"type": "keyboard", "action": "type"}])
                result = await browser_session_interact(mock_context, "test", actions)
                assert "missing 'text'" in result

                # Test unknown keyboard action
                actions = json.dumps([{"type": "keyboard", "action": "invalid", "key": "A"}])
                result = await browser_session_interact(mock_context, "test", actions)
                assert "Unknown keyboard action" in result


class TestKeyboardActionIntegration:
    """Test keyboard actions integrated with other browser actions."""

    @pytest.mark.asyncio
    async def test_mixed_actions(self, mock_context, mock_playwright):
        """Test keyboard actions mixed with click, wait, etc."""
        mock_pw, mock_keyboard, mock_page = mock_playwright

        with patch(
            "silica.developer.tools.browser_session_tools._check_playwright_available",
            return_value=(True, None),
        ):
            with patch(
                "silica.developer.tools.browser_session.async_playwright",
                return_value=mock_pw,
            ):
                manager = get_browser_session_manager()
                manager.sessions.clear()

                await browser_session_create(mock_context, "test")
                session = manager.get_session("test")
                session.page.keyboard = mock_keyboard

                # Simulate: click input, type text, press enter
                actions = json.dumps([
                    {"type": "click", "selector": "input#search"},
                    {"type": "keyboard", "action": "type", "text": "query"},
                    {"type": "keyboard", "action": "press", "key": "Enter"}
                ])

                result = await browser_session_interact(mock_context, "test", actions)

                assert "Clicked input#search" in result
                assert "Typed 'query'" in result
                assert "Pressed key 'Enter'" in result
                assert "Completed 3 actions" in result


class TestDocumentation:
    """Tests that verify the documentation examples are correct."""

    @pytest.mark.asyncio
    async def test_command_palette_example(self, mock_context, mock_playwright):
        """Test the command palette example from documentation."""
        mock_pw, mock_keyboard, mock_page = mock_playwright

        with patch(
            "silica.developer.tools.browser_session_tools._check_playwright_available",
            return_value=(True, None),
        ):
            with patch(
                "silica.developer.tools.browser_session.async_playwright",
                return_value=mock_pw,
            ):
                manager = get_browser_session_manager()
                manager.sessions.clear()

                await browser_session_create(mock_context, "test")
                session = manager.get_session("test")
                session.page.keyboard = mock_keyboard

                # From docs: Open palette, type, select
                actions = json.dumps([
                    {"type": "keyboard", "action": "press", "key": "Control+K"},
                    {"type": "wait", "ms": 100},
                    {"type": "keyboard", "action": "type", "text": "search query"},
                    {"type": "keyboard", "action": "press", "key": "Enter"}
                ])

                result = await browser_session_interact(mock_context, "test", actions)

                assert "Pressed key 'Control+K'" in result
                assert "Waited 100ms" in result
                assert "Typed 'search query'" in result
                assert "Pressed key 'Enter'" in result

    @pytest.mark.asyncio
    async def test_arrow_navigation_example(self, mock_context, mock_playwright):
        """Test the arrow key navigation example from documentation."""
        mock_pw, mock_keyboard, mock_page = mock_playwright

        with patch(
            "silica.developer.tools.browser_session_tools._check_playwright_available",
            return_value=(True, None),
        ):
            with patch(
                "silica.developer.tools.browser_session.async_playwright",
                return_value=mock_pw,
            ):
                manager = get_browser_session_manager()
                manager.sessions.clear()

                await browser_session_create(mock_context, "test")
                session = manager.get_session("test")
                session.page.keyboard = mock_keyboard

                # From docs: Arrow key navigation
                actions = json.dumps([
                    {"type": "keyboard", "action": "press", "key": "ArrowDown"},
                    {"type": "keyboard", "action": "press", "key": "ArrowDown"},
                    {"type": "keyboard", "action": "press", "key": "ArrowUp"}
                ])

                result = await browser_session_interact(mock_context, "test", actions)

                assert result.count("Pressed key 'ArrowDown'") == 2
                assert "Pressed key 'ArrowUp'" in result
