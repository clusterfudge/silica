"""Browser session management for stateful browser automation.

This module provides persistent browser sessions that can be used across
multiple tool invocations, enabling complex workflows like:
- Navigate to a page
- Interact with elements
- Inspect the resulting DOM
- Continue interacting based on results
"""

import atexit
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple


class BrowserSession:
    """Represents a single persistent browser session."""

    def __init__(
        self, name: str, viewport_width: int = 1920, viewport_height: int = 1080
    ):
        self.name = name
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.status = "active"  # active, error

        # Playwright objects (initialized on first use)
        self.playwright = None
        self.browser = None
        self.context = None  # Browser context for cookies/state
        self.page = None

        # State tracking
        self.current_url = None
        self.actions_performed = []

    async def initialize(self):
        """Initialize browser and page."""
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            viewport={"width": self.viewport_width, "height": self.viewport_height}
        )
        self.page = await self.context.new_page()
        self.last_activity = datetime.now()

    async def close(self):
        """Close browser and cleanup."""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            # Best effort cleanup
            print(f"Warning: Error during browser session cleanup: {e}")
        finally:
            self.status = "closed"

    def record_action(self, action_type: str, details: str):
        """Record an action performed in this session."""
        self.actions_performed.append(
            {
                "type": action_type,
                "details": details,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self.last_activity = datetime.now()

    def get_session_info(self) -> Dict:
        """Get session information for display."""
        return {
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "current_url": self.current_url,
            "viewport": f"{self.viewport_width}x{self.viewport_height}",
            "actions_count": len(self.actions_performed),
        }


class BrowserSessionManager:
    """Manages multiple browser sessions with cleanup."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern to ensure only one manager exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_sessions: int = 5):
        """Initialize the session manager."""
        if self._initialized:
            return

        self.sessions: Dict[str, BrowserSession] = {}
        self.max_sessions = max_sessions
        self.cleanup_registered = False

        # Register cleanup handler
        if not self.cleanup_registered:
            atexit.register(self.cleanup_all_sessions)
            self.cleanup_registered = True

        self._initialized = True

    def _validate_session_name(self, name: str) -> bool:
        """Validate session name contains only allowed characters."""
        return bool(re.match(r"^[a-zA-Z0-9_-]+$", name))

    async def create_session(
        self, name: str, viewport_width: int = 1920, viewport_height: int = 1080
    ) -> Tuple[bool, str]:
        """Create and initialize a new browser session.

        Args:
            name: Name for the session (alphanumeric, underscore, dash only)
            viewport_width: Width of the browser viewport in pixels
            viewport_height: Height of the browser viewport in pixels

        Returns:
            Tuple of (success: bool, message: str)
        """
        # Validate session name
        if not name or not self._validate_session_name(name):
            return (
                False,
                "Error: Invalid session name. Use only alphanumeric characters, underscores, and hyphens.",
            )

        # Check if session already exists
        if name in self.sessions:
            return False, f"Error: Session '{name}' already exists"

        # Check max sessions
        if len(self.sessions) >= self.max_sessions:
            return (
                False,
                f"Error: Maximum number of sessions ({self.max_sessions}) reached. Destroy an existing session first.",
            )

        try:
            # Create and initialize session
            session = BrowserSession(name, viewport_width, viewport_height)
            await session.initialize()
            self.sessions[name] = session

            return True, f"Browser session '{name}' created successfully"

        except Exception as e:
            return False, f"Error creating browser session: {str(e)}"

    def list_sessions(self) -> List[Dict]:
        """List all active browser sessions.

        Returns:
            List of session information dictionaries
        """
        return [session.get_session_info() for session in self.sessions.values()]

    async def destroy_session(self, name: str) -> Tuple[bool, str]:
        """Close and remove a browser session.

        Args:
            name: Name of the session to destroy

        Returns:
            Tuple of (success: bool, message: str)
        """
        if name not in self.sessions:
            return False, f"Error: Session '{name}' not found"

        try:
            session = self.sessions[name]
            await session.close()
            del self.sessions[name]
            return True, f"Session '{name}' destroyed successfully"

        except Exception as e:
            # Try to remove from dict anyway
            if name in self.sessions:
                del self.sessions[name]
            return False, f"Error destroying session (removed anyway): {str(e)}"

    def get_session(self, name: str) -> Optional[BrowserSession]:
        """Get a session by name.

        Args:
            name: Name of the session

        Returns:
            BrowserSession if found, None otherwise
        """
        return self.sessions.get(name)

    def cleanup_all_sessions(self):
        """Cleanup all sessions (called on exit)."""
        import asyncio

        if not self.sessions:
            return

        # Always create a fresh event loop for cleanup
        # The main loop may be closed or in an inconsistent state at exit time
        try:
            # Try to get existing loop and check if it's running/closed
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("Loop is closed")
            except RuntimeError:
                # No loop or loop is closed - create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Close all sessions
            for session in list(self.sessions.values()):
                try:
                    loop.run_until_complete(session.close())
                except Exception:
                    # Silently ignore errors during cleanup - we're exiting anyway
                    pass

            self.sessions.clear()
        except Exception:
            # Last resort - just clear the sessions dict
            # The browser process will be cleaned up by the OS
            self.sessions.clear()


# Global session manager instance
_session_manager = None


def get_browser_session_manager() -> BrowserSessionManager:
    """Get the global browser session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = BrowserSessionManager()
    return _session_manager
