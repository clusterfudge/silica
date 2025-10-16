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


def _check_playwright_available() -> tuple[bool, Optional[str]]:
    """Check if Playwright is available and installed.

    Returns:
        Tuple of (available: bool, error_message: Optional[str])
    """
    try:
        from playwright.sync_api import sync_playwright

        # Try to launch a browser to verify it's installed
        with sync_playwright() as p:
            # Check if chromium is installed
            try:
                browser = p.chromium.launch(headless=True)
                browser.close()
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
def screenshot_webpage(
    context: AgentContext,
    url: str,
    viewport_width: int = 1920,
    viewport_height: int = 1080,
    selector: Optional[str] = None,
    full_page: bool = False,
    wait_for: Optional[str] = None,
    output_format: str = "png",
) -> str:
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
    playwright_available, error_msg = _check_playwright_available()

    if not playwright_available:
        return f"Browser tools not available:\n{error_msg}"

    return _screenshot_local(
        url=url,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        selector=selector,
        full_page=full_page,
        wait_for=wait_for,
        output_format=output_format,
    )


def _screenshot_local(
    url: str,
    viewport_width: int,
    viewport_height: int,
    selector: Optional[str],
    full_page: bool,
    wait_for: Optional[str],
    output_format: str,
) -> str:
    """Take a screenshot using local Playwright browser."""
    from playwright.sync_api import sync_playwright

    scratchpad = _ensure_scratchpad()

    # Generate filename
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screenshot_{timestamp}.{output_format}"
    filepath = scratchpad / filename

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": viewport_width, "height": viewport_height}
            )

            # Navigate to URL
            page.goto(url, wait_until="domcontentloaded")

            # Wait for specific condition if requested
            if wait_for:
                if wait_for == "networkidle":
                    page.wait_for_load_state("networkidle", timeout=30000)
                else:
                    page.wait_for_selector(wait_for, timeout=30000)

            # Take screenshot
            screenshot_options = {"path": str(filepath), "type": output_format}
            if full_page:
                screenshot_options["full_page"] = True

            if selector:
                element = page.locator(selector)
                element.screenshot(**screenshot_options)
            else:
                page.screenshot(**screenshot_options)

            browser.close()

        # Read the file and encode as base64
        with open(filepath, "rb") as f:
            image_data = f.read()
            base64_data = base64.b64encode(image_data).decode("utf-8")

        return (
            f"Screenshot saved to: {filepath}\n"
            f"Size: {len(image_data)} bytes\n"
            f"Viewport: {viewport_width}x{viewport_height}\n"
            f"URL: {url}\n\n"
            f"Base64 encoded image:\n{base64_data[:100]}... (truncated for display)\n\n"
            f"You can view the full image at: {filepath.absolute()}"
        )

    except Exception as e:
        return f"Error taking screenshot: {str(e)}"


@tool
def browser_interact(
    context: AgentContext,
    url: str,
    actions: str,
    viewport_width: int = 1920,
    viewport_height: int = 1080,
    capture_screenshots: bool = True,
    capture_console: bool = True,
    timeout: int = 30000,
) -> str:
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
    playwright_available, error_msg = _check_playwright_available()

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

    from playwright.sync_api import sync_playwright

    scratchpad = _ensure_scratchpad()
    console_logs = []
    screenshots = []
    results = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
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
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            results.append(f"Navigated to: {url}")

            # Initial screenshot
            if capture_screenshots:
                from datetime import datetime

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}_initial.png"
                filepath = scratchpad / filename
                page.screenshot(path=str(filepath))
                screenshots.append(str(filepath.absolute()))

            # Execute actions
            for i, action in enumerate(actions_list):
                action_type = action.get("type")
                action_num = i + 1

                try:
                    if action_type == "click":
                        selector = action.get("selector")
                        page.click(selector, timeout=timeout)
                        results.append(f"Action {action_num}: Clicked {selector}")

                    elif action_type == "type":
                        selector = action.get("selector")
                        text = action.get("text", "")
                        page.fill(selector, text, timeout=timeout)
                        results.append(
                            f"Action {action_num}: Typed '{text}' into {selector}"
                        )

                    elif action_type == "select":
                        selector = action.get("selector")
                        value = action.get("value")
                        page.select_option(selector, value, timeout=timeout)
                        results.append(
                            f"Action {action_num}: Selected '{value}' in {selector}"
                        )

                    elif action_type == "hover":
                        selector = action.get("selector")
                        page.hover(selector, timeout=timeout)
                        results.append(f"Action {action_num}: Hovered over {selector}")

                    elif action_type == "wait":
                        wait_selector = action.get("selector")
                        wait_ms = action.get("ms")
                        if wait_selector:
                            page.wait_for_selector(wait_selector, timeout=timeout)
                            results.append(
                                f"Action {action_num}: Waited for {wait_selector}"
                            )
                        elif wait_ms:
                            page.wait_for_timeout(wait_ms)
                            results.append(f"Action {action_num}: Waited {wait_ms}ms")
                        else:
                            results.append(
                                f"Action {action_num}: Wait action missing selector or ms"
                            )

                    elif action_type == "scroll":
                        x = action.get("x", 0)
                        y = action.get("y", 0)
                        page.evaluate(f"window.scrollTo({x}, {y})")
                        results.append(f"Action {action_num}: Scrolled to ({x}, {y})")

                    elif action_type == "screenshot":
                        # Manual screenshot action
                        pass  # Will be captured below if capture_screenshots is True

                    elif action_type == "evaluate":
                        script = action.get("script", "")
                        result = page.evaluate(script)
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
                        page.screenshot(path=str(filepath))
                        screenshots.append(str(filepath.absolute()))

                except Exception as e:
                    results.append(f"Action {action_num}: ERROR - {str(e)}")

            browser.close()

        # Build response
        response_parts = [
            "Browser automation completed successfully!\n",
            "\n=== Actions Performed ===\n",
        ]
        response_parts.extend([f"  {r}\n" for r in results])

        if screenshots:
            response_parts.append("\n=== Screenshots Captured ===\n")
            response_parts.extend([f"  {s}\n" for s in screenshots])

        if console_logs:
            response_parts.append("\n=== Console Logs ===\n")
            for log in console_logs:
                response_parts.append(f"  [{log['type']}] {log['text']}\n")

        return "".join(response_parts)

    except Exception as e:
        return f"Error during browser automation: {str(e)}"


@tool
def get_browser_capabilities(context: AgentContext) -> str:
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
    playwright_available, error_msg = _check_playwright_available()

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
