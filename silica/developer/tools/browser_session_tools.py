"""Tools for stateful browser session management.

These tools enable persistent browser sessions that can be used across
multiple operations, allowing for complex workflows like navigate → interact →
inspect → repeat.
"""

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from silica.developer.context import AgentContext

from .browser_session import get_browser_session_manager
from .framework import tool


def _ensure_scratchpad() -> Path:
    """Ensure the .agent-scratchpad directory exists and return its path."""
    scratchpad = Path(".agent-scratchpad")
    scratchpad.mkdir(exist_ok=True)
    return scratchpad


async def _check_playwright_available() -> tuple[bool, Optional[str]]:
    """Check if Playwright is available and installed."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
                await browser.close()
                return True, None
            except Exception as e:
                if "Executable doesn't exist" in str(e):
                    return False, (
                        "Playwright is installed but browser binaries are missing.\n"
                        "Install with: playwright install chromium"
                    )
                return False, f"Playwright browser error: {str(e)}"
    except ImportError:
        return False, (
            "Playwright is not installed.\n"
            "Install with: pip install playwright && playwright install chromium"
        )
    except Exception as e:
        return False, f"Unexpected error checking Playwright: {str(e)}"


@tool
async def get_browser_capabilities(context: AgentContext) -> str:
    """Check what browser tools are available in the current environment.

    Returns information about whether Playwright is installed and browser binaries
    are available.
    """
    capabilities = {
        "playwright_installed": False,
        "browser_available": False,
        "tools_available": False,
        "details": [],
    }

    # Check Playwright
    playwright_available, error_msg = await _check_playwright_available()

    if playwright_available:
        capabilities["playwright_installed"] = True
        capabilities["browser_available"] = True
        capabilities["tools_available"] = True
        capabilities["details"].append("✓ Playwright installed and browser ready")
        capabilities["details"].append("✓ Browser session tools available")
    else:
        if "not installed" in error_msg:
            capabilities["details"].append("✗ Playwright not installed")
        elif "binaries are missing" in error_msg:
            capabilities["playwright_installed"] = True
            capabilities["details"].append("✓ Playwright installed")
            capabilities["details"].append("✗ Browser binaries missing")
        else:
            capabilities["details"].append(f"✗ Playwright error: {error_msg}")

    # Build response
    response = ["=== Browser Tool Capabilities ===\n"]
    response.append(
        f"Browser Tools: {'Available' if capabilities['tools_available'] else 'Not Available'}\n"
    )
    response.append("\n=== Details ===\n")
    response.extend([f"  {d}\n" for d in capabilities["details"]])

    if not capabilities["tools_available"]:
        response.append("\n=== Setup Instructions ===\n")
        response.append("To enable browser tools, install Playwright:\n")
        response.append("  pip install playwright\n")
        response.append("  playwright install chromium\n")

    return "".join(response)


@tool
async def browser_session_create(
    context: AgentContext,
    session_name: str,
    viewport_width: int = 1920,
    viewport_height: int = 1080,
) -> str:
    """Create a new persistent browser session.

    Creates a browser session that will remain open across multiple tool
    invocations, allowing for stateful workflows like navigate → interact →
    inspect → repeat.

    Args:
        session_name: Name for the session (alphanumeric, underscore, dash only)
        viewport_width: Width of the browser viewport in pixels (default: 1920)
        viewport_height: Height of the browser viewport in pixels (default: 1080)

    Returns:
        Success or error message
    """
    # Check if Playwright is available
    playwright_available, error_msg = await _check_playwright_available()
    if not playwright_available:
        return f"Browser tools not available:\n{error_msg}"

    # Create the session
    manager = get_browser_session_manager()
    success, message = await manager.create_session(
        session_name, viewport_width, viewport_height
    )

    return message


@tool
async def browser_session_navigate(
    context: AgentContext,
    session_name: str,
    url: str,
    wait_for: Optional[str] = None,
    timeout: int = 30000,
) -> str:
    """Navigate to a URL in an existing browser session.

    Args:
        session_name: Name of the browser session
        url: The URL to navigate to
        wait_for: CSS selector to wait for before returning, or "networkidle"
        timeout: Timeout for navigation in milliseconds (default: 30000)

    Returns:
        Success or error message with page information
    """
    manager = get_browser_session_manager()
    session = manager.get_session(session_name)

    if not session:
        return f"Error: Session '{session_name}' not found"

    try:
        await session.page.goto(url, wait_until="domcontentloaded", timeout=timeout)

        if wait_for:
            if wait_for == "networkidle":
                await session.page.wait_for_load_state("networkidle", timeout=timeout)
            else:
                await session.page.wait_for_selector(wait_for, timeout=timeout)

        # Get page title
        title = await session.page.title()

        session.current_url = url
        session.record_action("navigate", f"Navigated to {url}")

        return f"Successfully navigated to: {url}\nPage title: {title}"

    except Exception as e:
        session.status = "error"
        return f"Error navigating to {url}: {str(e)}"


@tool
async def browser_session_interact(
    context: AgentContext,
    session_name: str,
    actions: str,
    timeout: int = 30000,
) -> str:
    """Perform browser interactions in an existing session.

    Executes a sequence of actions (click, type, select, etc.) in the
    current page state of the session.

    Args:
        session_name: Name of the browser session
        actions: JSON string containing list of actions to perform
        timeout: Default timeout for actions in milliseconds (default: 30000)

    Actions format:
        [
            {"type": "click", "selector": "button#submit"},
            {"type": "type", "selector": "input#username", "text": "admin"},
            {"type": "select", "selector": "select#country", "value": "US"},
            {"type": "hover", "selector": ".menu-item"},
            {"type": "wait", "selector": ".loading", "ms": 1000},
            {"type": "scroll", "x": 0, "y": 500},
            {"type": "evaluate", "script": "document.title"}
        ]

    Returns:
        Summary of actions performed and results
    """
    manager = get_browser_session_manager()
    session = manager.get_session(session_name)

    if not session:
        return f"Error: Session '{session_name}' not found"

    # Parse actions
    try:
        actions_list = json.loads(actions)
        if not isinstance(actions_list, list):
            return "Error: actions must be a JSON array of action objects"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in actions parameter: {str(e)}"

    results = []
    page = session.page

    try:
        for i, action in enumerate(actions_list):
            action_type = action.get("type")
            action_num = i + 1

            try:
                if action_type == "click":
                    selector = action.get("selector")
                    await page.click(selector, timeout=timeout)
                    results.append(f"Action {action_num}: Clicked {selector}")

                elif action_type == "type":
                    selector = action.get("selector")
                    text = action.get("text", "")
                    await page.fill(selector, text, timeout=timeout)
                    results.append(f"Action {action_num}: Typed into {selector}")

                elif action_type == "select":
                    selector = action.get("selector")
                    value = action.get("value")
                    await page.select_option(selector, value, timeout=timeout)
                    results.append(
                        f"Action {action_num}: Selected '{value}' in {selector}"
                    )

                elif action_type == "hover":
                    selector = action.get("selector")
                    await page.hover(selector, timeout=timeout)
                    results.append(f"Action {action_num}: Hovered over {selector}")

                elif action_type == "wait":
                    wait_selector = action.get("selector")
                    wait_ms = action.get("ms")
                    if wait_selector:
                        await page.wait_for_selector(wait_selector, timeout=timeout)
                        results.append(
                            f"Action {action_num}: Waited for {wait_selector}"
                        )
                    elif wait_ms:
                        await page.wait_for_timeout(wait_ms)
                        results.append(f"Action {action_num}: Waited {wait_ms}ms")
                    else:
                        results.append(
                            f"Action {action_num}: Wait action missing selector or ms"
                        )

                elif action_type == "scroll":
                    x = action.get("x", 0)
                    y = action.get("y", 0)
                    await page.evaluate(f"window.scrollTo({x}, {y})")
                    results.append(f"Action {action_num}: Scrolled to ({x}, {y})")

                elif action_type == "evaluate":
                    script = action.get("script", "")
                    result = await page.evaluate(script)
                    results.append(
                        f"Action {action_num}: Evaluated script, result: {result}"
                    )

                else:
                    results.append(
                        f"Action {action_num}: Unknown action type '{action_type}'"
                    )

            except Exception as e:
                results.append(f"Action {action_num}: ERROR - {str(e)}")

        # Record action in session
        session.record_action("interact", f"Performed {len(actions_list)} actions")

        return (
            f"Completed {len(actions_list)} actions in session '{session_name}':\n\n"
            + "\n".join(results)
        )

    except Exception as e:
        session.status = "error"
        return f"Error during browser interaction: {str(e)}"


@tool
async def browser_session_inspect(
    context: AgentContext,
    session_name: str,
    selector: Optional[str] = None,
    element_id: Optional[str] = None,
    timeout: int = 30000,
) -> str:
    """Inspect DOM elements in the current page state of a browser session.

    Args:
        session_name: Name of the browser session
        selector: CSS selector to query (e.g., "button", ".class-name", "#id")
        element_id: Element ID to look up directly (alternative to selector)
        timeout: Timeout for operations in milliseconds (default: 30000)

    Returns:
        JSON string with element information
    """
    # Validate parameters
    if not selector and not element_id:
        return json.dumps(
            {"error": "Either 'selector' or 'element_id' parameter must be provided"},
            indent=2,
        )

    if selector and element_id:
        return json.dumps(
            {"error": "Only one of 'selector' or 'element_id' can be provided"},
            indent=2,
        )

    # Convert element_id to selector
    if element_id:
        selector = f"#{element_id}"

    manager = get_browser_session_manager()
    session = manager.get_session(session_name)

    if not session:
        return json.dumps({"error": f"Session '{session_name}' not found"}, indent=2)

    try:
        page = session.page

        # Query elements
        elements = page.locator(selector)
        count = await elements.count()

        if count == 0:
            return json.dumps(
                {
                    "session": session_name,
                    "url": session.current_url,
                    "selector": selector,
                    "count": 0,
                    "message": "No elements found matching selector",
                },
                indent=2,
            )

        # Extract information (limit to 50 elements)
        max_elements = min(count, 50)
        element_data = []

        for i in range(max_elements):
            element = elements.nth(i)
            try:
                tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
                text_content = await element.text_content()
                inner_html = await element.inner_html()

                attributes = await element.evaluate(
                    """el => {
                        const attrs = {};
                        for (let attr of el.attributes) {
                            attrs[attr.name] = attr.value;
                        }
                        return attrs;
                    }"""
                )

                is_visible = await element.is_visible()
                is_enabled = (
                    await element.is_enabled()
                    if tag_name in ["button", "input", "select", "textarea"]
                    else None
                )

                element_info = {
                    "index": i,
                    "tag": tag_name,
                    "text": text_content.strip() if text_content else "",
                    "attributes": attributes,
                    "innerHTML": inner_html[:200]
                    + ("..." if len(inner_html) > 200 else ""),
                    "visible": is_visible,
                }

                if is_enabled is not None:
                    element_info["enabled"] = is_enabled

                element_data.append(element_info)

            except Exception as e:
                element_data.append({"index": i, "error": str(e)})

        session.record_action("inspect", f"Inspected {selector}")

        result = {
            "session": session_name,
            "url": session.current_url,
            "selector": selector,
            "count": count,
            "showing": max_elements,
            "elements": element_data,
        }

        if count > max_elements:
            result["message"] = f"Showing first {max_elements} of {count} elements"

        return json.dumps(result, indent=2)

    except Exception as e:
        session.status = "error"
        return json.dumps(
            {"error": f"Error inspecting DOM: {str(e)}", "session": session_name},
            indent=2,
        )


@tool
async def browser_session_screenshot(
    context: AgentContext,
    session_name: str,
    selector: Optional[str] = None,
    full_page: bool = False,
) -> list:
    """Take a screenshot of the current page state in a browser session.

    Args:
        session_name: Name of the browser session
        selector: Optional CSS selector to screenshot a specific element
        full_page: If True, captures the entire scrollable page (default: False)

    Returns:
        List containing text description and image data
    """
    manager = get_browser_session_manager()
    session = manager.get_session(session_name)

    if not session:
        return f"Error: Session '{session_name}' not found"

    scratchpad = _ensure_scratchpad()

    try:
        page = session.page

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{session_name}_{timestamp}.png"
        filepath = scratchpad / filename

        # Take screenshot
        screenshot_options = {"path": str(filepath), "type": "png"}
        if full_page:
            screenshot_options["full_page"] = True

        if selector:
            element = page.locator(selector)
            await element.screenshot(**screenshot_options)
        else:
            await page.screenshot(**screenshot_options)

        # Read and encode
        with open(filepath, "rb") as f:
            image_data = f.read()
            base64_data = base64.b64encode(image_data).decode("utf-8")

        session.record_action("screenshot", f"Screenshot saved to {filename}")

        return [
            {
                "type": "text",
                "text": (
                    f"Screenshot captured from session '{session_name}'!\n"
                    f"URL: {session.current_url}\n"
                    f"Viewport: {session.viewport_width}x{session.viewport_height}\n"
                    f"Size: {len(image_data)} bytes\n"
                    f"Saved to: {filepath.absolute()}"
                ),
            },
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64_data,
                },
            },
        ]

    except Exception as e:
        session.status = "error"
        return f"Error taking screenshot: {str(e)}"


@tool
def browser_session_list(context: AgentContext) -> str:
    """List all active browser sessions.

    Returns:
        Formatted table of session information
    """
    manager = get_browser_session_manager()
    sessions = manager.list_sessions()

    if not sessions:
        return "No active browser sessions."

    result = "## Active Browser Sessions\n\n"
    result += "| Name | Status | URL | Viewport | Actions | Created | Last Activity |\n"
    result += "|------|--------|-----|----------|---------|---------|---------------|\n"

    for session in sessions:
        created = session["created_at"][:16].replace("T", " ")
        last_activity = session["last_activity"][:16].replace("T", " ")
        url = session["current_url"] or "(not navigated)"
        # Truncate long URLs
        if len(url) > 40:
            url = url[:37] + "..."

        result += (
            f"| {session['name']} | {session['status']} | {url} | "
            f"{session['viewport']} | {session['actions_count']} | "
            f"{created} | {last_activity} |\n"
        )

    return result


@tool
async def browser_session_destroy(context: AgentContext, session_name: str) -> str:
    """Close and destroy a browser session.

    Args:
        session_name: Name of the session to destroy

    Returns:
        Success or error message
    """
    manager = get_browser_session_manager()
    success, message = await manager.destroy_session(session_name)
    return message


@tool
async def browser_session_get_info(context: AgentContext, session_name: str) -> str:
    """Get detailed information about a browser session.

    Args:
        session_name: Name of the browser session

    Returns:
        JSON string with session information
    """
    manager = get_browser_session_manager()
    session = manager.get_session(session_name)

    if not session:
        return json.dumps({"error": f"Session '{session_name}' not found"}, indent=2)

    try:
        page = session.page
        url = await page.url()
        title = await page.title()

        info = session.get_session_info()
        info["page_title"] = title
        info["page_url"] = url

        # Get recent actions
        recent_actions = session.actions_performed[-5:]  # Last 5 actions
        info["recent_actions"] = recent_actions

        return json.dumps(info, indent=2)

    except Exception as e:
        return json.dumps(
            {"error": f"Error getting session info: {str(e)}", "session": session_name},
            indent=2,
        )
