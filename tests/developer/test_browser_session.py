"""Tests for browser session management."""

import json
import pytest
from unittest.mock import Mock, AsyncMock, patch

from silica.developer.tools.browser_session import (
    BrowserSession,
    BrowserSessionManager,
    get_browser_session_manager,
)
from silica.developer.tools.browser_session_tools import (
    browser_session_create,
    browser_session_navigate,
    browser_session_interact,
    browser_session_inspect,
    browser_session_list,
    browser_session_destroy,
    browser_session_get_info,
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
    # Cleanup after each test
    manager = get_browser_session_manager()
    # Close all sessions
    for session_name in list(manager.sessions.keys()):
        try:
            await manager.destroy_session(session_name)
        except Exception:
            pass
    manager.sessions.clear()


@pytest.fixture
async def mock_playwright():
    """Create mock Playwright objects."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.click = AsyncMock()
    mock_page.fill = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_page.locator = Mock()
    mock_page.title = AsyncMock(return_value="Test Page")
    mock_page.url = AsyncMock(return_value="http://localhost:8000")

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_playwright.stop = AsyncMock()

    return mock_playwright


class TestBrowserSession:
    """Tests for BrowserSession class."""

    def test_browser_session_init(self):
        """Test BrowserSession initialization."""
        session = BrowserSession("test", viewport_width=1024, viewport_height=768)

        assert session.name == "test"
        assert session.viewport_width == 1024
        assert session.viewport_height == 768
        assert session.status == "active"
        assert session.current_url is None
        assert len(session.actions_performed) == 0

    @pytest.mark.asyncio
    async def test_browser_session_initialize(self, mock_playwright):
        """Test browser session initialization."""
        session = BrowserSession("test")

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_playwright,
        ):
            await session.initialize()

        assert session.playwright is not None
        assert session.browser is not None
        assert session.context is not None
        assert session.page is not None

    def test_record_action(self):
        """Test recording actions."""
        session = BrowserSession("test")

        session.record_action("navigate", "http://example.com")
        session.record_action("click", "button#submit")

        assert len(session.actions_performed) == 2
        assert session.actions_performed[0]["type"] == "navigate"
        assert session.actions_performed[1]["details"] == "button#submit"

    def test_get_session_info(self):
        """Test getting session information."""
        session = BrowserSession("test", 1920, 1080)
        session.current_url = "http://example.com"
        session.record_action("test", "action")

        info = session.get_session_info()

        assert info["name"] == "test"
        assert info["status"] == "active"
        assert info["current_url"] == "http://example.com"
        assert info["viewport"] == "1920x1080"
        assert info["actions_count"] == 1


class TestBrowserSessionManager:
    """Tests for BrowserSessionManager class."""

    def test_manager_singleton(self):
        """Test that manager is a singleton."""
        manager1 = BrowserSessionManager()
        manager2 = BrowserSessionManager()

        assert manager1 is manager2

    def test_validate_session_name(self):
        """Test session name validation."""
        manager = BrowserSessionManager()

        assert manager._validate_session_name("valid_name-123")
        assert manager._validate_session_name("test")
        assert not manager._validate_session_name("invalid name")
        assert not manager._validate_session_name("invalid@name")
        assert not manager._validate_session_name("")

    @pytest.mark.asyncio
    async def test_create_session_success(self, mock_playwright):
        """Test successful session creation."""
        manager = BrowserSessionManager()
        manager.sessions.clear()  # Clear any existing sessions

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_playwright,
        ):
            success, message = await manager.create_session("test", 1920, 1080)

        assert success is True
        assert "created successfully" in message
        assert "test" in manager.sessions

    @pytest.mark.asyncio
    async def test_create_session_invalid_name(self):
        """Test session creation with invalid name."""
        manager = BrowserSessionManager()

        success, message = await manager.create_session("invalid name")

        assert success is False
        assert "Invalid session name" in message

    @pytest.mark.asyncio
    async def test_create_session_duplicate(self, mock_playwright):
        """Test creating duplicate session."""
        manager = BrowserSessionManager()
        manager.sessions.clear()

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_playwright,
        ):
            await manager.create_session("test")
            success, message = await manager.create_session("test")

        assert success is False
        assert "already exists" in message

    @pytest.mark.asyncio
    async def test_create_session_max_limit(self, mock_playwright):
        """Test max session limit."""
        manager = get_browser_session_manager()
        manager.sessions.clear()
        # Temporarily override max_sessions for this test
        original_max = manager.max_sessions
        manager.max_sessions = 2

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_playwright,
        ):
            await manager.create_session("test1")
            await manager.create_session("test2")
            success, message = await manager.create_session("test3")

        assert success is False
        assert "Maximum number" in message

        # Restore original max
        manager.max_sessions = original_max

    def test_list_sessions(self):
        """Test listing sessions."""
        manager = BrowserSessionManager()
        manager.sessions.clear()

        # Add mock sessions
        session1 = BrowserSession("test1")
        session2 = BrowserSession("test2")
        manager.sessions["test1"] = session1
        manager.sessions["test2"] = session2

        sessions = manager.list_sessions()

        assert len(sessions) == 2
        assert any(s["name"] == "test1" for s in sessions)
        assert any(s["name"] == "test2" for s in sessions)

    @pytest.mark.asyncio
    async def test_destroy_session(self):
        """Test destroying a session."""
        manager = BrowserSessionManager()
        manager.sessions.clear()

        # Add mock session
        session = BrowserSession("test")
        session.close = AsyncMock()
        manager.sessions["test"] = session

        success, message = await manager.destroy_session("test")

        assert success is True
        assert "destroyed successfully" in message
        assert "test" not in manager.sessions

    @pytest.mark.asyncio
    async def test_destroy_nonexistent_session(self):
        """Test destroying non-existent session."""
        manager = BrowserSessionManager()
        manager.sessions.clear()

        success, message = await manager.destroy_session("nonexistent")

        assert success is False
        assert "not found" in message

    def test_get_session(self):
        """Test getting a session."""
        manager = BrowserSessionManager()
        manager.sessions.clear()

        session = BrowserSession("test")
        manager.sessions["test"] = session

        retrieved = manager.get_session("test")
        assert retrieved is session

        not_found = manager.get_session("nonexistent")
        assert not_found is None


class TestBrowserSessionTools:
    """Tests for browser session tools."""

    @pytest.mark.asyncio
    async def test_browser_session_create_tool(self, mock_context, mock_playwright):
        """Test browser_session_create tool."""
        with patch(
            "silica.developer.tools.browser_session_tools._check_playwright_available",
            return_value=(True, None),
        ):
            with patch(
                "playwright.async_api.async_playwright",
                return_value=mock_playwright,
            ):
                # Clear sessions
                manager = get_browser_session_manager()
                manager.sessions.clear()

                result = await browser_session_create(mock_context, session_name="test")

        assert "created successfully" in result
        assert "test" in manager.sessions

        # Cleanup
        await manager.destroy_session("test")

    @pytest.mark.asyncio
    async def test_browser_session_create_playwright_unavailable(self, mock_context):
        """Test browser_session_create when Playwright unavailable."""
        with patch(
            "silica.developer.tools.browser_session_tools._check_playwright_available",
            return_value=(False, "Playwright not installed"),
        ):
            result = await browser_session_create(mock_context, session_name="test")

        assert "not available" in result

    @pytest.mark.asyncio
    async def test_browser_session_navigate(self, mock_context, mock_playwright):
        """Test browser_session_navigate tool."""
        manager = get_browser_session_manager()
        manager.sessions.clear()

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_playwright,
        ):
            # Create session
            await manager.create_session("test")

            # Navigate
            result = await browser_session_navigate(
                mock_context, session_name="test", url="http://example.com"
            )

        assert "Successfully navigated" in result
        assert "http://example.com" in result

        # Cleanup
        await manager.destroy_session("test")

    @pytest.mark.asyncio
    async def test_browser_session_navigate_not_found(self, mock_context):
        """Test navigating in non-existent session."""
        result = await browser_session_navigate(
            mock_context, session_name="nonexistent", url="http://example.com"
        )

        assert "not found" in result

    @pytest.mark.asyncio
    async def test_browser_session_interact(self, mock_context, mock_playwright):
        """Test browser_session_interact tool."""
        manager = get_browser_session_manager()
        manager.sessions.clear()

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_playwright,
        ):
            await manager.create_session("test")

            actions = json.dumps(
                [
                    {"type": "click", "selector": "button"},
                    {"type": "type", "selector": "input", "text": "test"},
                ]
            )

            result = await browser_session_interact(
                mock_context, session_name="test", actions=actions
            )

        assert "Completed 2 actions" in result

        await manager.destroy_session("test")

    @pytest.mark.asyncio
    async def test_browser_session_inspect(self, mock_context, mock_playwright):
        """Test browser_session_inspect tool."""
        manager = get_browser_session_manager()
        manager.sessions.clear()

        # Setup mock locator
        mock_element = AsyncMock()
        mock_element.evaluate = AsyncMock(side_effect=["button", {"id": "test"}])
        mock_element.text_content = AsyncMock(return_value="Click me")
        mock_element.inner_html = AsyncMock(return_value="Click me")
        mock_element.is_visible = AsyncMock(return_value=True)
        mock_element.is_enabled = AsyncMock(return_value=True)

        mock_locator = Mock()
        mock_locator.count = AsyncMock(return_value=1)
        mock_locator.nth = Mock(return_value=mock_element)

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_playwright,
        ):
            await manager.create_session("test")

            # Now override the page's locator method
            session = manager.get_session("test")
            session.page.locator = Mock(return_value=mock_locator)
            session.current_url = "http://test.com"

            result = await browser_session_inspect(
                mock_context, session_name="test", selector="button"
            )

        result_data = json.loads(result)
        assert result_data["count"] == 1
        assert result_data["session"] == "test"

        await manager.destroy_session("test")

    @pytest.mark.asyncio
    async def test_browser_session_list_empty(self, mock_context):
        """Test listing sessions when none exist."""
        manager = get_browser_session_manager()
        manager.sessions.clear()

        result = browser_session_list(mock_context)

        assert "No active browser sessions" in result

    @pytest.mark.asyncio
    async def test_browser_session_list_with_sessions(
        self, mock_context, mock_playwright
    ):
        """Test listing sessions."""
        manager = get_browser_session_manager()
        manager.sessions.clear()

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_playwright,
        ):
            await manager.create_session("test1")
            await manager.create_session("test2")

            result = browser_session_list(mock_context)

        assert "test1" in result
        assert "test2" in result
        assert "Active Browser Sessions" in result

        await manager.destroy_session("test1")
        await manager.destroy_session("test2")

    @pytest.mark.asyncio
    async def test_browser_session_destroy_tool(self, mock_context, mock_playwright):
        """Test browser_session_destroy tool."""
        manager = get_browser_session_manager()
        manager.sessions.clear()

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_playwright,
        ):
            await manager.create_session("test")

            result = await browser_session_destroy(mock_context, session_name="test")

        assert "destroyed successfully" in result
        assert "test" not in manager.sessions

    @pytest.mark.asyncio
    async def test_browser_session_get_info(self, mock_context, mock_playwright):
        """Test browser_session_get_info tool."""
        manager = get_browser_session_manager()
        manager.sessions.clear()

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_playwright,
        ):
            await manager.create_session("test")

            # Setup the page mock methods
            session = manager.get_session("test")
            session.page.url = AsyncMock(return_value="http://test.com")
            session.page.title = AsyncMock(return_value="Test Page")

            result = await browser_session_get_info(mock_context, session_name="test")

        result_data = json.loads(result)
        assert result_data["name"] == "test"
        assert "page_title" in result_data
        assert result_data["page_title"] == "Test Page"

        await manager.destroy_session("test")
