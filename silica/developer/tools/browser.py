"""Browser capability checking.

This module provides tools for checking browser automation availability.
For browser automation, use the browser_session_* tools.
"""

from typing import Optional
from silica.developer.context import AgentContext
from .framework import tool


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
