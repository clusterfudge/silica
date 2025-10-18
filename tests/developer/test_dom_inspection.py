"""Tests for DOM inspection tool."""

import json
import pytest
from unittest.mock import Mock, AsyncMock, patch
from silica.developer.tools.browser import inspect_dom
from silica.developer.context import AgentContext


@pytest.fixture
def mock_context():
    """Create a mock AgentContext."""
    return Mock(spec=AgentContext)


@pytest.mark.asyncio
async def test_inspect_dom_basic(mock_context):
    """Test basic DOM inspection functionality."""
    
    # Mock Playwright and page interactions
    mock_element = AsyncMock()
    mock_element.count = AsyncMock(return_value=2)
    mock_element.nth = Mock()  # nth() is not async in Playwright
    
    # Mock first element
    mock_first = AsyncMock()
    mock_first.evaluate = AsyncMock(side_effect=[
        "button",  # tag name
        {"class": "btn btn-primary", "id": "submit-btn"}  # attributes
    ])
    mock_first.text_content = AsyncMock(return_value="Submit")
    mock_first.inner_html = AsyncMock(return_value="Submit")
    mock_first.is_visible = AsyncMock(return_value=True)
    mock_first.is_enabled = AsyncMock(return_value=True)
    
    # Mock second element
    mock_second = AsyncMock()
    mock_second.evaluate = AsyncMock(side_effect=[
        "button",  # tag name
        {"class": "btn btn-secondary", "id": "cancel-btn"}  # attributes
    ])
    mock_second.text_content = AsyncMock(return_value="Cancel")
    mock_second.inner_html = AsyncMock(return_value="Cancel")
    mock_second.is_visible = AsyncMock(return_value=True)
    mock_second.is_enabled = AsyncMock(return_value=True)
    
    # Configure nth() to return appropriate mock
    def nth_side_effect(index):
        return mock_first if index == 0 else mock_second
    
    mock_element.nth.side_effect = nth_side_effect
    
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.locator = Mock(return_value=mock_element)
    
    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()
    
    mock_playwright = AsyncMock()
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    
    with patch("silica.developer.tools.browser._check_playwright_available", return_value=(True, None)):
        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            result = await inspect_dom(
                mock_context,
                url="http://localhost:8000",
                selector="button"
            )
    
    # Parse result and verify
    result_data = json.loads(result)
    assert result_data["count"] == 2
    assert result_data["selector"] == "button"
    assert result_data["url"] == "http://localhost:8000"
    assert len(result_data["elements"]) == 2


@pytest.mark.asyncio
async def test_inspect_dom_no_elements(mock_context):
    """Test DOM inspection when no elements are found."""
    
    mock_element = AsyncMock()
    mock_element.count = AsyncMock(return_value=0)
    
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.locator = Mock(return_value=mock_element)
    
    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()
    
    mock_playwright = AsyncMock()
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    
    with patch("silica.developer.tools.browser._check_playwright_available", return_value=(True, None)):
        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            result = await inspect_dom(
                mock_context,
                url="http://localhost:8000",
                selector=".nonexistent"
            )
    
    result_data = json.loads(result)
    assert result_data["count"] == 0
    assert "No elements found" in result_data["message"]


@pytest.mark.asyncio
async def test_inspect_dom_playwright_not_available(mock_context):
    """Test error handling when Playwright is not available."""
    
    with patch("silica.developer.tools.browser._check_playwright_available", 
               return_value=(False, "Playwright is not installed.")):
        result = await inspect_dom(
            mock_context,
            url="http://localhost:8000",
            selector="button"
        )
    
    assert "Browser tools not available" in result
    assert "Playwright is not installed" in result


@pytest.mark.asyncio
async def test_inspect_dom_with_wait_for(mock_context):
    """Test DOM inspection with wait_for option."""
    
    mock_element = AsyncMock()
    mock_element.count = AsyncMock(return_value=1)
    mock_element.nth = Mock()  # nth() is not async in Playwright
    
    mock_first = AsyncMock()
    mock_first.evaluate = AsyncMock(side_effect=[
        "div",  # tag name
        {"class": "content"}  # attributes
    ])
    mock_first.text_content = AsyncMock(return_value="Content loaded")
    mock_first.inner_html = AsyncMock(return_value="Content loaded")
    mock_first.is_visible = AsyncMock(return_value=True)
    
    mock_element.nth.return_value = mock_first
    
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.locator = Mock(return_value=mock_element)
    
    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()
    
    mock_playwright = AsyncMock()
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    
    with patch("silica.developer.tools.browser._check_playwright_available", return_value=(True, None)):
        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            result = await inspect_dom(
                mock_context,
                url="http://localhost:8000",
                selector=".content",
                wait_for=".content"
            )
    
    # Verify wait_for_selector was called
    mock_page.wait_for_selector.assert_called_once()
    
    result_data = json.loads(result)
    assert result_data["count"] == 1


@pytest.mark.asyncio
async def test_inspect_dom_limits_to_50_elements(mock_context):
    """Test that DOM inspection limits results to 50 elements."""
    
    mock_element = AsyncMock()
    mock_element.count = AsyncMock(return_value=100)  # More than 50
    mock_element.nth = Mock()  # nth() is not async in Playwright
    
    # Create a mock element that can be returned multiple times
    mock_nth_element = AsyncMock()
    mock_nth_element.evaluate = AsyncMock(side_effect=lambda script: "div" if "tagName" in script else {})
    mock_nth_element.text_content = AsyncMock(return_value="Item")
    mock_nth_element.inner_html = AsyncMock(return_value="<span>Item</span>")
    mock_nth_element.is_visible = AsyncMock(return_value=True)
    
    mock_element.nth.return_value = mock_nth_element
    
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.locator = Mock(return_value=mock_element)
    
    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()
    
    mock_playwright = AsyncMock()
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    
    with patch("silica.developer.tools.browser._check_playwright_available", return_value=(True, None)):
        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            result = await inspect_dom(
                mock_context,
                url="http://localhost:8000",
                selector="div"
            )
    
    result_data = json.loads(result)
    assert result_data["count"] == 100
    assert result_data["showing"] == 50
    assert len(result_data["elements"]) == 50
    assert "Showing first 50 of 100 elements" in result_data["message"]


@pytest.mark.asyncio
async def test_inspect_dom_with_element_id(mock_context):
    """Test DOM inspection using element_id parameter."""
    
    mock_element = AsyncMock()
    mock_element.count = AsyncMock(return_value=1)
    mock_element.nth = Mock()  # nth() is not async in Playwright
    
    mock_first = AsyncMock()
    mock_first.evaluate = AsyncMock(side_effect=[
        "div",  # tag name
        {"id": "my-element", "class": "content"}  # attributes
    ])
    mock_first.text_content = AsyncMock(return_value="Element content")
    mock_first.inner_html = AsyncMock(return_value="Element content")
    mock_first.is_visible = AsyncMock(return_value=True)
    
    mock_element.nth.return_value = mock_first
    
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.locator = Mock(return_value=mock_element)
    
    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()
    
    mock_playwright = AsyncMock()
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    
    with patch("silica.developer.tools.browser._check_playwright_available", return_value=(True, None)):
        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            result = await inspect_dom(
                mock_context,
                url="http://localhost:8000",
                element_id="my-element"
            )
    
    # Verify the locator was called with the correct selector (#my-element)
    mock_page.locator.assert_called_once_with("#my-element")
    
    result_data = json.loads(result)
    assert result_data["count"] == 1
    assert result_data["selector"] == "#my-element"


@pytest.mark.asyncio
async def test_inspect_dom_requires_selector_or_id(mock_context):
    """Test that either selector or element_id must be provided."""
    
    with patch("silica.developer.tools.browser._check_playwright_available", return_value=(True, None)):
        # No selector or element_id
        result = await inspect_dom(
            mock_context,
            url="http://localhost:8000"
        )
    
    result_data = json.loads(result)
    assert "error" in result_data
    assert "must be provided" in result_data["error"]


@pytest.mark.asyncio
async def test_inspect_dom_not_both_selector_and_id(mock_context):
    """Test that both selector and element_id cannot be provided together."""
    
    with patch("silica.developer.tools.browser._check_playwright_available", return_value=(True, None)):
        # Both selector and element_id
        result = await inspect_dom(
            mock_context,
            url="http://localhost:8000",
            selector="button",
            element_id="my-button"
        )
    
    result_data = json.loads(result)
    assert "error" in result_data
    assert "not both" in result_data["error"].lower()


@pytest.mark.asyncio
async def test_inspect_dom_handles_element_errors(mock_context):
    """Test that DOM inspection handles errors gracefully for individual elements."""
    
    mock_element = AsyncMock()
    mock_element.count = AsyncMock(return_value=2)
    mock_element.nth = Mock()  # nth() is not async in Playwright
    
    # First element works fine
    mock_first = AsyncMock()
    mock_first.evaluate = AsyncMock(side_effect=[
        "div",
        {"class": "good"}
    ])
    mock_first.text_content = AsyncMock(return_value="Good element")
    mock_first.inner_html = AsyncMock(return_value="Good element")
    mock_first.is_visible = AsyncMock(return_value=True)
    
    # Second element raises an error
    mock_second = AsyncMock()
    mock_second.evaluate = AsyncMock(side_effect=Exception("Element not found"))
    
    def nth_side_effect(index):
        return mock_first if index == 0 else mock_second
    
    mock_element.nth.side_effect = nth_side_effect
    
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.locator = Mock(return_value=mock_element)
    
    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()
    
    mock_playwright = AsyncMock()
    mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.__aexit__ = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    
    with patch("silica.developer.tools.browser._check_playwright_available", return_value=(True, None)):
        with patch("playwright.async_api.async_playwright", return_value=mock_playwright):
            result = await inspect_dom(
                mock_context,
                url="http://localhost:8000",
                selector="div"
            )
    
    result_data = json.loads(result)
    assert result_data["count"] == 2
    assert len(result_data["elements"]) == 2
    # First element should have proper data
    assert result_data["elements"][0]["tag"] == "div"
    # Second element should have error
    assert "error" in result_data["elements"][1]
    assert "Element not found" in result_data["elements"][1]["error"]
