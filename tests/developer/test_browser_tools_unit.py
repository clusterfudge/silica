"""Unit tests for browser tools that don't require Playwright installation."""

import os
import json
import pytest
from unittest.mock import Mock, patch
from silica.developer.context import AgentContext
from silica.developer.tools.browser import (
    screenshot_webpage,
    browser_interact,
    get_browser_capabilities,
    _ensure_scratchpad,
)


@pytest.fixture
def mock_context():
    """Create a mock AgentContext."""
    return Mock(spec=AgentContext)


@pytest.fixture
def scratchpad_dir(tmp_path):
    """Create a temporary scratchpad directory."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path / ".agent-scratchpad"
    os.chdir(original_cwd)


class TestScratchpadManagement:
    """Tests for scratchpad directory management."""

    def test_ensure_scratchpad_creates_directory(self, tmp_path):
        """Test that _ensure_scratchpad creates the directory if it doesn't exist."""
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            scratchpad = _ensure_scratchpad()
            assert scratchpad.exists()
            assert scratchpad.is_dir()
            assert scratchpad.name == ".agent-scratchpad"
        finally:
            os.chdir(original_cwd)

    def test_ensure_scratchpad_idempotent(self, tmp_path):
        """Test that _ensure_scratchpad is idempotent."""
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            scratchpad1 = _ensure_scratchpad()
            scratchpad2 = _ensure_scratchpad()
            assert scratchpad1 == scratchpad2
            assert scratchpad1.exists()
        finally:
            os.chdir(original_cwd)


class TestGetBrowserCapabilities:
    """Tests for get_browser_capabilities tool."""

    @pytest.mark.asyncio
    async def test_capabilities_playwright_available(self, mock_context):
        """Test capabilities report when Playwright is available."""
        from unittest.mock import AsyncMock

        mock_check = AsyncMock(return_value=(True, None))
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            mock_check,
        ):
            result = await get_browser_capabilities(mock_context)
            assert "Browser Tools: Available" in result
            assert "Playwright installed and browser ready" in result
            assert "screenshot_webpage available" in result
            assert "browser_interact available" in result

    @pytest.mark.asyncio
    async def test_capabilities_no_playwright(self, mock_context):
        """Test capabilities report when Playwright is not available."""
        from unittest.mock import AsyncMock

        error_msg = "Playwright is not installed"
        mock_check = AsyncMock(return_value=(False, error_msg))
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            mock_check,
        ):
            result = await get_browser_capabilities(mock_context)
            assert "Browser Tools: Not Available" in result
            assert "Setup Instructions" in result


class TestScreenshotWebpage:
    """Tests for screenshot_webpage tool."""

    @pytest.mark.asyncio
    async def test_screenshot_no_playwright(self, mock_context, scratchpad_dir):
        """Test screenshot fails gracefully when Playwright is not available."""
        from unittest.mock import AsyncMock

        mock_check = AsyncMock(
            return_value=(
                False,
                "Playwright is not installed.\nInstall with: pip install playwright && playwright install chromium",
            )
        )
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            mock_check,
        ):
            result = await screenshot_webpage(mock_context, "http://example.com")
            assert "Browser tools not available" in result
            assert "pip install playwright" in result


class TestBrowserInteract:
    """Tests for browser_interact tool."""

    @pytest.mark.asyncio
    async def test_interact_no_playwright(self, mock_context):
        """Test browser_interact fails gracefully without Playwright."""
        from unittest.mock import AsyncMock

        mock_check = AsyncMock(return_value=(False, "Playwright is not installed"))
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            mock_check,
        ):
            result = await browser_interact(
                mock_context,
                "http://example.com",
                json.dumps([{"type": "click", "selector": "#button"}]),
            )
            assert "Browser automation not available" in result

    @pytest.mark.asyncio
    async def test_interact_invalid_json(self, mock_context):
        """Test browser_interact handles invalid JSON."""
        from unittest.mock import AsyncMock

        mock_check = AsyncMock(return_value=(True, None))
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            mock_check,
        ):
            result = await browser_interact(
                mock_context, "http://example.com", "not valid json"
            )
            assert "Invalid JSON" in result

    @pytest.mark.asyncio
    async def test_interact_not_array(self, mock_context):
        """Test browser_interact requires array of actions."""
        from unittest.mock import AsyncMock

        mock_check = AsyncMock(return_value=(True, None))
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            mock_check,
        ):
            result = await browser_interact(
                mock_context, "http://example.com", json.dumps({"type": "click"})
            )
            assert "must be a JSON array" in result
