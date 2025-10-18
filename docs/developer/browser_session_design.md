# Browser Session Design

## Problem
Current browser tools (`screenshot_webpage`, `browser_interact`, `inspect_dom`) open a new browser for each operation, then close it. This makes it impossible to:
1. Navigate to a page
2. Interact with it (click buttons, fill forms)
3. Inspect the DOM to see what changed
4. Continue interacting based on inspection results

## Solution
Implement stateful browser sessions similar to the shell session tools (tmux-based).

## Architecture Pattern (from shell_session tools)

### Session Management Components

1. **BrowserSession class** - Represents a single browser session
   - Stores browser and page objects
   - Tracks session state (URL, created time, last activity)
   - Maintains session configuration (viewport size, etc.)

2. **BrowserSessionManager class** - Manages multiple browser sessions
   - Creates and destroys sessions
   - Maintains a dictionary of active sessions
   - Handles cleanup on exit
   - Validates session names

3. **Session Tools** - Tools that interact with sessions
   - `browser_session_create` - Create a new browser session
   - `browser_session_navigate` - Navigate to a URL in an existing session
   - `browser_session_interact` - Perform actions (click, type, etc.)
   - `browser_session_inspect` - Inspect DOM in current page state
   - `browser_session_screenshot` - Take screenshot of current state
   - `browser_session_get_url` - Get current URL and page info
   - `browser_session_list` - List all active sessions
   - `browser_session_destroy` - Close and cleanup a session

## Detailed Design

### BrowserSession Class
```python
class BrowserSession:
    def __init__(self, name: str, viewport_width: int = 1920, viewport_height: int = 1080):
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
        """Initialize browser and page"""
        from playwright.async_api import async_playwright
        
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            viewport={"width": self.viewport_width, "height": self.viewport_height}
        )
        self.page = await self.context.new_page()
        
    async def close(self):
        """Close browser and cleanup"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
```

### BrowserSessionManager Class
```python
class BrowserSessionManager:
    def __init__(self, max_sessions: int = 5):
        self.sessions: Dict[str, BrowserSession] = {}
        self.max_sessions = max_sessions
        
    async def create_session(self, name: str, viewport_width: int = 1920, viewport_height: int = 1080):
        """Create and initialize a new browser session"""
        if len(self.sessions) >= self.max_sessions:
            return False, "Maximum number of sessions reached"
            
        if name in self.sessions:
            return False, f"Session '{name}' already exists"
            
        session = BrowserSession(name, viewport_width, viewport_height)
        await session.initialize()
        self.sessions[name] = session
        return True, f"Browser session '{name}' created successfully"
        
    def list_sessions(self):
        """List all active sessions"""
        return [
            {
                "name": s.name,
                "status": s.status,
                "created_at": s.created_at.isoformat(),
                "last_activity": s.last_activity.isoformat(),
                "current_url": s.current_url,
                "actions_count": len(s.actions_performed),
            }
            for s in self.sessions.values()
        ]
        
    async def destroy_session(self, name: str):
        """Close and remove a session"""
        if name not in self.sessions:
            return False, f"Session '{name}' not found"
            
        session = self.sessions[name]
        await session.close()
        del self.sessions[name]
        return True, f"Session '{name}' destroyed"
```

### Tool Functions

All tools follow the pattern:
1. Get session manager (singleton)
2. Get the specified session
3. Perform operation on session's page
4. Update session state
5. Return result

Example:
```python
@tool
async def browser_session_navigate(
    context: AgentContext,
    session_name: str,
    url: str,
    wait_for: Optional[str] = None,
    timeout: int = 30000,
) -> str:
    """Navigate to a URL in an existing browser session."""
    manager = get_browser_session_manager()
    
    if session_name not in manager.sessions:
        return f"Error: Session '{session_name}' not found"
        
    session = manager.sessions[session_name]
    
    try:
        await session.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        
        if wait_for:
            if wait_for == "networkidle":
                await session.page.wait_for_load_state("networkidle", timeout=timeout)
            else:
                await session.page.wait_for_selector(wait_for, timeout=timeout)
        
        session.current_url = url
        session.last_activity = datetime.now()
        
        return f"Navigated to: {url}"
    except Exception as e:
        return f"Error navigating to {url}: {str(e)}"
```

## Key Differences from Shell Sessions

1. **Async everywhere** - Playwright is async, so all operations must be async
2. **Resource intensive** - Browsers use more memory, so lower max_sessions (5 vs 10)
3. **No output buffering** - Browser sessions don't have stdout/stderr
4. **State is visual** - Can take screenshots to see current state
5. **Context management** - Browser context maintains cookies, localStorage, etc.

## Migration Path

### Phase 1: Create session infrastructure
- [ ] Create `browser_session.py` with BrowserSession and BrowserSessionManager classes
- [ ] Create session management tools (create, list, destroy)
- [ ] Add tests for session management

### Phase 2: Add session-based operations
- [ ] `browser_session_navigate` - Navigate in session
- [ ] `browser_session_interact` - Perform actions in session
- [ ] `browser_session_inspect` - Inspect DOM in session
- [ ] `browser_session_screenshot` - Screenshot in session
- [ ] Add tests for operations

### Phase 3: Keep existing tools for convenience
- Existing tools remain for one-off operations
- Document when to use session vs one-off tools

## Example Usage

```python
# Create a session
await browser_session_create(context, session_name="test", viewport_width=1920)

# Navigate to a page
await browser_session_navigate(context, session_name="test", url="http://localhost:8000")

# Interact with the page
await browser_session_interact(
    context,
    session_name="test",
    actions='[{"type": "click", "selector": "#login-button"}]'
)

# Inspect the result
result = await browser_session_inspect(context, session_name="test", selector=".error-message")

# Take a screenshot to see what happened
await browser_session_screenshot(context, session_name="test")

# Continue working...
await browser_session_interact(
    context,
    session_name="test",
    actions='[{"type": "type", "selector": "#username", "text": "admin"}]'
)

# Clean up when done
await browser_session_destroy(context, session_name="test")
```

## Benefits

1. **Stateful workflows** - Can build complex interaction sequences
2. **Debugging** - Can inspect DOM after each action
3. **Efficiency** - Don't pay browser startup cost for each operation
4. **Context preservation** - Cookies, localStorage, session storage maintained
5. **Realistic testing** - Simulates actual user workflows

## Implementation Notes

- Use global singleton for session manager (like shell sessions)
- Register atexit handler for cleanup
- Add proper error handling for Playwright exceptions
- Consider adding session timeout/idle cleanup
- Add tool to get current URL/page title/state
