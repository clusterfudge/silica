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

    def test_capabilities_playwright_available(self, mock_context):
        """Test capabilities report when Playwright is available."""
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            return_value=(True, None),
        ):
            result = get_browser_capabilities(mock_context)
            assert "Screenshot Tool: Available" in result
            assert "Browser Automation: Available" in result
            assert "Playwright installed and browser ready" in result

    def test_capabilities_no_playwright(self, mock_context):
        """Test capabilities report when Playwright is not available."""
        error_msg = "Playwright is not installed"
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            return_value=(False, error_msg),
        ):
            result = get_browser_capabilities(mock_context)
            assert "Screenshot Tool: Not Available" in result
            assert "Browser Automation: Not Available" in result
            assert "Setup Instructions" in result

    def test_capabilities_with_api_fallback(self, mock_context):
        """Test capabilities report when API fallback is configured."""
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            return_value=(False, "Not installed"),
        ):
            with patch.dict(
                os.environ, {"SCREENSHOT_API_URL": "https://example.com/screenshot"}
            ):
                result = get_browser_capabilities(mock_context)
                assert "Screenshot Tool: Available" in result
                assert "API fallback configured" in result


class TestScreenshotWebpage:
    """Tests for screenshot_webpage tool."""

    def test_screenshot_no_playwright_no_api(self, mock_context, scratchpad_dir):
        """Test screenshot fails gracefully when nothing is available."""
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            return_value=(
                False,
                "Playwright is not installed.\nInstall with: pip install playwright && playwright install chromium",
            ),
        ):
            result = screenshot_webpage(mock_context, "http://example.com")
            assert "Browser tools not available" in result
            assert "pip install playwright" in result

    def test_screenshot_with_api_fallback(self, mock_context, scratchpad_dir, tmp_path):
        """Test screenshot uses API fallback when Playwright unavailable."""
        mock_response = Mock()
        mock_response.content = b"fake_image_data"

        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            return_value=(False, "Not installed"),
        ):
            with patch.dict(
                os.environ, {"SCREENSHOT_API_URL": "https://example.com/screenshot"}
            ):
                with patch("httpx.post", return_value=mock_response):
                    result = screenshot_webpage(mock_context, "http://example.com")
                    assert "Screenshot saved to" in result
                    assert "External API" in result


class TestBrowserInteract:
    """Tests for browser_interact tool."""

    def test_interact_no_playwright(self, mock_context):
        """Test browser_interact fails gracefully without Playwright."""
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            return_value=(False, "Playwright is not installed"),
        ):
            result = browser_interact(
                mock_context,
                "http://example.com",
                json.dumps([{"type": "click", "selector": "#button"}]),
            )
            assert "Browser automation not available" in result

    def test_interact_invalid_json(self, mock_context):
        """Test browser_interact handles invalid JSON."""
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            return_value=(True, None),
        ):
            result = browser_interact(
                mock_context, "http://example.com", "not valid json"
            )
            assert "Invalid JSON" in result

    def test_interact_not_array(self, mock_context):
        """Test browser_interact requires array of actions."""
        with patch(
            "silica.developer.tools.browser._check_playwright_available",
            return_value=(True, None),
        ):
            result = browser_interact(
                mock_context, "http://example.com", json.dumps({"type": "click"})
            )
            assert "must be a JSON array" in result
