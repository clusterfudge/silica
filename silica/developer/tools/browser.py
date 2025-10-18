"""Browser automation and screenshot tools for web development.

This module provides tools for taking screenshots of web pages and automating
browser interactions. It uses Playwright for local browser automation with
optional fallback to external screenshot services for headless environments.
"""

import base64
import json
from pathlib import Path
from typing import Optional
from silica.developer.context import AgentContext
from .framework import tool


def _ensure_scratchpad() -> Path:
    """Ensure the .agent-scratchpad directory exists and return its path."""
    scratchpad = Path(".agent-scratchpad")
    scratchpad.mkdir(exist_ok=True)
    return scratchpad


async def _check_playwright_available() -> tuple[bool, Optional[str]]:
    """Check if Playwright is available and installed.

    Returns:
        Tuple of (available: bool, error_message: Optional[str])
    """
    try:
        from playwright.async_api import async_playwright

        # Try to launch a browser to verify it's installed
        async with async_playwright() as p:
            # Check if chromium is installed
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
async def screenshot_webpage(
    context: AgentContext,
    url: str,
    viewport_width: int = 1920,
    viewport_height: int = 1080,
    selector: Optional[str] = None,
    full_page: bool = False,
    wait_for: Optional[str] = None,
    output_format: str = "png",
) -> list:
    """Take a screenshot of a webpage.

    This tool captures a visual representation of a webpage, allowing you to see
    what you've built. Requires Playwright to be installed.

    Args:
        url: The URL to screenshot (can be local like http://localhost:8000 or remote)
        viewport_width: Width of the browser viewport in pixels (default: 1920)
        viewport_height: Height of the browser viewport in pixels (default: 1080)
        selector: CSS selector to screenshot a specific element instead of the whole page
        full_page: If True, captures the entire scrollable page (default: False)
        wait_for: CSS selector to wait for before taking screenshot, or "networkidle"
        output_format: Image format - "png" or "jpeg" (default: png)
    """
    # Check if Playwright is available
    playwright_available, error_msg = await _check_playwright_available()

    if not playwright_available:
        return f"Browser tools not available:\n{error_msg}"

    return await _screenshot_local(
        url=url,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        selector=selector,
        full_page=full_page,
        wait_for=wait_for,
        output_format=output_format,
    )


async def _screenshot_local(
    url: str,
    viewport_width: int,
    viewport_height: int,
    selector: Optional[str],
    full_page: bool,
    wait_for: Optional[str],
    output_format: str,
) -> list:
    """Take a screenshot using local Playwright browser."""
    from playwright.async_api import async_playwright

    scratchpad = _ensure_scratchpad()

    # Generate filename
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screenshot_{timestamp}.{output_format}"
    filepath = scratchpad / filename

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={"width": viewport_width, "height": viewport_height}
            )

            # Navigate to URL
            await page.goto(url, wait_until="domcontentloaded")

            # Wait for specific condition if requested
            if wait_for:
                if wait_for == "networkidle":
                    await page.wait_for_load_state("networkidle", timeout=30000)
                else:
                    await page.wait_for_selector(wait_for, timeout=30000)

            # Take screenshot
            screenshot_options = {"path": str(filepath), "type": output_format}
            if full_page:
                screenshot_options["full_page"] = True

            if selector:
                element = page.locator(selector)
                await element.screenshot(**screenshot_options)
            else:
                await page.screenshot(**screenshot_options)

            await browser.close()

        # Read the file and encode as base64
        with open(filepath, "rb") as f:
            image_data = f.read()
            base64_data = base64.b64encode(image_data).decode("utf-8")

        # Return both text description and image
        # Claude can view the image directly!
        return [
            {
                "type": "text",
                "text": (
                    f"Screenshot captured successfully!\n"
                    f"URL: {url}\n"
                    f"Viewport: {viewport_width}x{viewport_height}\n"
                    f"Size: {len(image_data)} bytes\n"
                    f"Saved to: {filepath.absolute()}"
                ),
            },
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": f"image/{output_format}",
                    "data": base64_data,
                },
            },
        ]

    except Exception as e:
        return f"Error taking screenshot: {str(e)}"


@tool
async def browser_interact(
    context: AgentContext,
    url: str,
    actions: str,
    viewport_width: int = 1920,
    viewport_height: int = 1080,
    capture_screenshots: bool = True,
    capture_console: bool = True,
    timeout: int = 30000,
) -> list:
    """Automate browser interactions and test web applications.

    This tool allows you to interact with web pages: click buttons, fill forms,
    navigate, and capture the results. Useful for testing functionality and
    validating that your web applications work correctly.

    Args:
        url: The URL to interact with
        actions: JSON string containing list of actions to perform (see below for format)
        viewport_width: Width of the browser viewport in pixels (default: 1920)
        viewport_height: Height of the browser viewport in pixels (default: 1080)
        capture_screenshots: If True, captures screenshots after each action (default: True)
        capture_console: If True, captures console logs (default: True)
        timeout: Default timeout for actions in milliseconds (default: 30000)
    """
    # Check if Playwright is available (no API fallback for interaction)
    playwright_available, error_msg = await _check_playwright_available()

    if not playwright_available:
        return (
            f"Browser automation not available:\n{error_msg}\n\n"
            "Browser automation requires local Playwright installation."
        )

    # Parse actions
    try:
        actions_list = json.loads(actions)
        if not isinstance(actions_list, list):
            return "Error: actions must be a JSON array of action objects"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in actions parameter: {str(e)}"

    from playwright.async_api import async_playwright

    scratchpad = _ensure_scratchpad()
    console_logs = []
    screenshots = []
    results = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={"width": viewport_width, "height": viewport_height}
            )

            # Capture console logs if requested
            if capture_console:
                page.on(
                    "console",
                    lambda msg: console_logs.append(
                        {"type": msg.type, "text": msg.text}
                    ),
                )

            # Navigate to URL
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            results.append(f"Navigated to: {url}")

            # Initial screenshot
            if capture_screenshots:
                from datetime import datetime

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}_initial.png"
                filepath = scratchpad / filename
                await page.screenshot(path=str(filepath))
                screenshots.append(str(filepath.absolute()))

            # Execute actions
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
                        results.append(
                            f"Action {action_num}: Typed '{text}' into {selector}"
                        )

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

                    elif action_type == "screenshot":
                        # Manual screenshot action
                        pass  # Will be captured below if capture_screenshots is True

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
                        continue

                    # Capture screenshot after action if requested
                    if capture_screenshots:
                        from datetime import datetime

                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        filename = f"screenshot_{timestamp}_action{action_num}.png"
                        filepath = scratchpad / filename
                        await page.screenshot(path=str(filepath))
                        screenshots.append(str(filepath.absolute()))

                except Exception as e:
                    results.append(f"Action {action_num}: ERROR - {str(e)}")

            await browser.close()

        # Build text summary
        text_parts = [
            "Browser automation completed successfully!\n",
            "\n=== Actions Performed ===\n",
        ]
        text_parts.extend([f"  {r}\n" for r in results])

        if console_logs:
            text_parts.append("\n=== Console Logs ===\n")
            for log in console_logs:
                text_parts.append(f"  [{log['type']}] {log['text']}\n")

        # Build content blocks - text first, then images
        content_blocks = [{"type": "text", "text": "".join(text_parts)}]

        # Add screenshot images if captured
        if screenshots:
            text_parts.append(
                f"\n=== {len(screenshots)} Screenshots Captured (shown below) ===\n"
            )
            for screenshot_path in screenshots:
                try:
                    with open(screenshot_path, "rb") as f:
                        image_data = f.read()
                        base64_data = base64.b64encode(image_data).decode("utf-8")
                        content_blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": base64_data,
                                },
                            }
                        )
                except Exception as e:
                    text_parts.append(f"  Error loading {screenshot_path}: {e}\n")

        return content_blocks

    except Exception as e:
        return f"Error during browser automation: {str(e)}"


@tool
async def inspect_dom(
    context: AgentContext,
    url: str,
    selector: Optional[str] = None,
    element_id: Optional[str] = None,
    viewport_width: int = 1920,
    viewport_height: int = 1080,
    wait_for: Optional[str] = None,
    timeout: int = 30000,
) -> str:
    """Inspect DOM elements on a webpage using CSS selectors or element ID.

    This tool allows you to query and inspect DOM elements to understand the
    structure and content of a webpage. Useful for debugging, testing, and
    understanding what elements are present.

    Args:
        url: The URL to inspect
        selector: CSS selector to query (e.g., "button", ".class-name", "#id")
        element_id: Element ID to look up directly (alternative to selector)
        viewport_width: Width of the browser viewport in pixels (default: 1920)
        viewport_height: Height of the browser viewport in pixels (default: 1080)
        wait_for: CSS selector to wait for before inspecting, or "networkidle"
        timeout: Timeout for page load and wait operations in milliseconds (default: 30000)

    Returns:
        JSON string with information about matching elements including:
        - count: number of elements found
        - elements: list of element details (tag, text, attributes, innerHTML)

    Note: Either selector or element_id must be provided (not both).
    """
    # Validate parameters
    if not selector and not element_id:
        return json.dumps(
            {
                "error": "Either 'selector' or 'element_id' parameter must be provided",
                "url": url,
            },
            indent=2,
        )

    if selector and element_id:
        return json.dumps(
            {
                "error": "Only one of 'selector' or 'element_id' can be provided, not both",
                "url": url,
            },
            indent=2,
        )

    # If element_id is provided, convert it to a selector
    if element_id:
        selector = f"#{element_id}"

    # Check if Playwright is available
    playwright_available, error_msg = await _check_playwright_available()

    if not playwright_available:
        return f"Browser tools not available:\n{error_msg}"

    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={"width": viewport_width, "height": viewport_height}
            )

            # Navigate to URL
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)

            # Wait for specific condition if requested
            if wait_for:
                if wait_for == "networkidle":
                    await page.wait_for_load_state("networkidle", timeout=timeout)
                else:
                    await page.wait_for_selector(wait_for, timeout=timeout)

            # Query elements using the selector
            elements = page.locator(selector)
            count = await elements.count()

            if count == 0:
                await browser.close()
                return json.dumps(
                    {
                        "url": url,
                        "selector": selector,
                        "count": 0,
                        "message": "No elements found matching selector",
                    },
                    indent=2,
                )

            # Extract information about each element (limit to first 50 to avoid huge responses)
            max_elements = min(count, 50)
            element_data = []

            for i in range(max_elements):
                element = elements.nth(i)
                try:
                    # Get element information
                    tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
                    text_content = await element.text_content()
                    inner_html = await element.inner_html()

                    # Get all attributes
                    attributes = await element.evaluate(
                        """el => {
                            const attrs = {};
                            for (let attr of el.attributes) {
                                attrs[attr.name] = attr.value;
                            }
                            return attrs;
                        }"""
                    )

                    # Get computed styles for visibility
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
                        + (
                            "..." if len(inner_html) > 200 else ""
                        ),  # Truncate long HTML
                        "visible": is_visible,
                    }

                    if is_enabled is not None:
                        element_info["enabled"] = is_enabled

                    element_data.append(element_info)

                except Exception as e:
                    element_data.append(
                        {
                            "index": i,
                            "error": f"Could not extract data: {str(e)}",
                        }
                    )

            await browser.close()

            result = {
                "url": url,
                "selector": selector,
                "count": count,
                "showing": max_elements,
                "elements": element_data,
            }

            if count > max_elements:
                result["message"] = f"Showing first {max_elements} of {count} elements"

            return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps(
            {
                "error": f"Error inspecting DOM: {str(e)}",
                "url": url,
                "selector": selector,
            },
            indent=2,
        )


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
        capabilities["details"].append("✓ screenshot_webpage available")
        capabilities["details"].append("✓ browser_interact available")
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
