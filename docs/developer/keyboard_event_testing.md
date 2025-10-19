# Keyboard Event Testing in Browser Sessions

## The Problem: Untrusted Events

When testing keyboard interactions in web browsers, you may encounter an issue where dispatched keyboard events don't trigger event handlers. This happens because browsers mark JavaScript-dispatched events as "untrusted" for security reasons.

### What Are Trusted vs Untrusted Events?

```javascript
// This event is marked as isTrusted: false
const event = new KeyboardEvent('keydown', { key: 'k', ctrlKey: true });
document.dispatchEvent(event);
console.log(event.isTrusted); // false

// Real user keyboard input would be isTrusted: true
// (can't be created via JavaScript)
```

### Why This Security Exists

Browsers intentionally prevent synthetic keyboard events from being "trusted" to protect users from:
- Malicious websites simulating system shortcuts (Ctrl+W to close tabs, Ctrl+T for new tabs)
- Clipboard manipulation (Ctrl+C, Ctrl+V)
- Form submission via Enter key
- Browser UI interaction via F11, Alt+F4, etc.

This is **by design** and cannot be bypassed through normal JavaScript APIs.

## Solutions for Testing

### Solution 1: Playwright's Keyboard API (Recommended for Integration Tests)

Playwright provides a native keyboard API that simulates real user keyboard input. These events are treated as trusted by the browser.

#### Adding Keyboard Support to Browser Sessions

We've extended the `browser_session_interact` tool to support keyboard actions:

```python
from silica.developer.tools.browser_session_tools import browser_session_interact
from silica.developer.context import AgentContext

# Example: Test command palette shortcut (Ctrl+K)
actions = json.dumps([
    {"type": "keyboard", "action": "press", "key": "Control+K"},
    {"type": "wait", "ms": 100},
    {"type": "keyboard", "action": "type", "text": "search query"},
    {"type": "keyboard", "action": "press", "key": "Enter"}
])

result = await browser_session_interact(
    context,
    session_name="test",
    actions=actions
)
```

#### Keyboard Action Types

```python
# Press a key (down + up)
{"type": "keyboard", "action": "press", "key": "Enter"}
{"type": "keyboard", "action": "press", "key": "Control+K"}
{"type": "keyboard", "action": "press", "key": "Meta+Shift+P"}  # Cmd+Shift+P on Mac

# Type text character by character
{"type": "keyboard", "action": "type", "text": "hello world"}

# Hold/release keys for combinations
{"type": "keyboard", "action": "down", "key": "Shift"}
{"type": "keyboard", "action": "press", "key": "A"}
{"type": "keyboard", "action": "up", "key": "Shift"}

# Insert text instantly (no keystroke events)
{"type": "keyboard", "action": "insertText", "text": "pasted content"}
```

#### Key Names

Playwright accepts standard key names:
- **Modifier Keys**: `Control`, `Alt`, `Shift`, `Meta` (Cmd on Mac, Win on Windows)
- **Navigation**: `ArrowUp`, `ArrowDown`, `ArrowLeft`, `ArrowRight`, `Home`, `End`, `PageUp`, `PageDown`
- **Special Keys**: `Enter`, `Escape`, `Tab`, `Backspace`, `Delete`, `Space`
- **Function Keys**: `F1` through `F12`
- **Letters/Numbers**: `a-z`, `A-Z`, `0-9`

Combinations use `+`: `Control+Shift+K`, `Meta+P`, etc.

#### Full Example: Testing Command Palette

```python
import pytest
import json
from silica.developer.tools.browser_session_tools import (
    browser_session_create,
    browser_session_navigate,
    browser_session_interact,
    browser_session_inspect
)

@pytest.mark.asyncio
async def test_command_palette_keyboard_shortcut(mock_context):
    """Test that Ctrl+K opens the command palette."""
    
    # Create and navigate to app
    await browser_session_create(mock_context, "test")
    await browser_session_navigate(
        mock_context,
        "test",
        "http://localhost:8000"
    )
    
    # Verify command palette is not visible initially
    result = await browser_session_inspect(
        mock_context,
        "test",
        selector="#command-palette"
    )
    assert '"visible": false' in result
    
    # Press Ctrl+K to open command palette
    actions = json.dumps([
        {"type": "keyboard", "action": "press", "key": "Control+K"}
    ])
    await browser_session_interact(mock_context, "test", actions)
    
    # Verify command palette is now visible
    result = await browser_session_inspect(
        mock_context,
        "test",
        selector="#command-palette"
    )
    assert '"visible": true' in result
```

### Solution 2: Direct Handler Testing (Recommended for Unit Tests)

For unit tests or when you need to test event handlers without a real browser, you can invoke the handlers directly using Playwright's `evaluate()` function.

```python
@pytest.mark.asyncio
async def test_keyboard_handler_directly(mock_context):
    """Test keyboard handler function directly."""
    
    # Navigate to page
    await browser_session_navigate(
        mock_context,
        "test",
        "http://localhost:8000"
    )
    
    # Test the handler directly by evaluating JavaScript
    actions = json.dumps([
        {
            "type": "evaluate",
            "script": """
                (() => {
                    // Simulate the event object the handler expects
                    const event = {
                        key: 'ArrowDown',
                        ctrlKey: false,
                        metaKey: false,
                        preventDefault: () => {},
                        stopPropagation: () => {}
                    };
                    
                    // Call the handler directly
                    handleKeydown(event);
                    
                    // Return the result state
                    return {
                        selectedIndex: getSelectedIndex(),
                        isPaletteOpen: isCommandPaletteOpen()
                    };
                })()
            """
        }
    ])
    
    result = await browser_session_interact(mock_context, "test", actions)
    
    # Parse and verify result
    assert "selectedIndex" in result
```

#### Pros and Cons

**Direct Handler Testing:**
- ✅ Works with mocked browsers
- ✅ Faster execution
- ✅ No browser security restrictions
- ❌ Doesn't test full event flow
- ❌ May miss event binding issues
- ❌ Not testing real user interaction

**Playwright Keyboard API:**
- ✅ Tests real user interaction
- ✅ Generates trusted events
- ✅ Tests complete event flow
- ❌ Requires real browser
- ❌ Slower execution
- ❌ More complex setup

### Solution 3: Hybrid Approach (Best Practice)

Use both approaches strategically:

1. **Unit Tests**: Test event handlers directly using `evaluate()`
2. **Integration Tests**: Use Playwright keyboard API for end-to-end flows
3. **CI/CD**: Run unit tests on every commit, integration tests on PR

```python
# Unit test - fast, mocked
@pytest.mark.unit
async def test_arrow_key_navigation_handler():
    """Unit test for arrow key handler logic."""
    result = await page.evaluate('''() => {
        const handler = window.keyHandlers.arrowDown;
        return handler({key: 'ArrowDown', preventDefault: () => {}});
    }''')
    assert result['selectedIndex'] == 1

# Integration test - slow, real browser
@pytest.mark.integration  
@pytest.mark.slow
async def test_arrow_key_navigation_e2e():
    """Integration test for arrow key navigation with real keyboard."""
    await page.keyboard.press('ArrowDown')
    selected = await page.evaluate('() => getSelectedIndex()')
    assert selected == 1
```

## Testing Keyboard Navigation in Log Viewer

The log viewer (`scripts/log_viewer_static/app.js`) has keyboard navigation. Here's how to test it:

```python
@pytest.mark.asyncio
async def test_log_viewer_keyboard_navigation(mock_context):
    """Test log viewer keyboard navigation."""
    
    # Setup
    await browser_session_create(mock_context, "viewer")
    await browser_session_navigate(
        mock_context,
        "viewer",
        "http://localhost:5000"
    )
    
    # Wait for logs to load
    actions = json.dumps([
        {"type": "wait", "selector": ".log-entry", "timeout": 5000}
    ])
    await browser_session_interact(mock_context, "viewer", actions)
    
    # Test arrow down navigation
    actions = json.dumps([
        {"type": "keyboard", "action": "press", "key": "ArrowDown"},
        {"type": "wait", "ms": 100},
        {"type": "keyboard", "action": "press", "key": "ArrowDown"}
    ])
    await browser_session_interact(mock_context, "viewer", actions)
    
    # Verify selection moved
    result = await browser_session_inspect(
        mock_context,
        "viewer",
        selector=".log-entry.selected"
    )
    data = json.loads(result)
    assert data['count'] == 1
    assert data['elements'][0]['attributes']['data-index'] == '2'
```

## Platform Differences: Ctrl vs Cmd

Playwright automatically handles platform differences between Windows/Linux (Ctrl) and macOS (Cmd/Meta):

```python
# This works on all platforms
# - Windows/Linux: Uses Ctrl
# - macOS: Uses Command/Meta
actions = json.dumps([
    {"type": "keyboard", "action": "press", "key": "ControlOrMeta+K"}
])

# Or be explicit for each platform
import sys
modifier = "Meta" if sys.platform == "darwin" else "Control"
actions = json.dumps([
    {"type": "keyboard", "action": "press", "key": f"{modifier}+K"}
])
```

## Common Pitfalls

### 1. Event Not Firing - Element Not Focused

```python
# WRONG: Element might not have focus
await page.keyboard.press('Enter')

# RIGHT: Ensure element has focus first
await page.click('input#search')  # Focuses the input
await page.keyboard.press('Enter')

# OR: Explicitly focus
await page.focus('input#search')
await page.keyboard.press('Enter')
```

### 2. Timing Issues

```python
# WRONG: Actions happen too fast
await page.keyboard.press('Control+K')
await page.keyboard.type('search')

# RIGHT: Add small delays for animations/state updates
actions = json.dumps([
    {"type": "keyboard", "action": "press", "key": "Control+K"},
    {"type": "wait", "ms": 200},  # Wait for palette to open
    {"type": "keyboard", "action": "type", "text": "search"}
])
```

### 3. Modifier Key State

```python
# WRONG: Holding shift doesn't work across actions
await page.keyboard.down('Shift')
await page.click('button')  # Shift not applied to click
await page.keyboard.up('Shift')

# RIGHT: Use press with modifiers
actions = json.dumps([
    {"type": "keyboard", "action": "press", "key": "Shift+Enter"}
])
```

## Best Practices

1. **Use Real Keyboard API for Critical Paths**: Command palettes, shortcuts, form submission
2. **Test Handlers Directly for Logic**: Arrow navigation logic, key code mapping
3. **Add Explicit Waits**: Allow time for animations, state updates, API calls
4. **Focus Elements First**: Ensure keyboard target has focus
5. **Test on Multiple Platforms**: Ctrl vs Cmd differences matter
6. **Document Keyboard Shortcuts**: In tests and user docs
7. **Verify Element State**: Check visibility, enabled state before interaction

## Further Reading

- [Playwright Keyboard API](https://playwright.dev/python/docs/input#keyboard)
- [MDN: Trusted Events](https://developer.mozilla.org/en-US/docs/Web/API/Event/isTrusted)
- [Web Security: Keyboard Event Security](https://w3c.github.io/uievents/#trusted-events)
- Browser Session Tools: `silica/developer/tools/browser_session_tools.py`

## Summary

| Scenario | Solution | Example |
|----------|----------|---------|
| Integration tests with real browser | Playwright keyboard API | `{"type": "keyboard", "action": "press", "key": "Control+K"}` |
| Unit tests without browser | Direct handler evaluation | `page.evaluate('() => handleKey({key: "k"})')` |
| Command palette shortcuts | Playwright keyboard API | `page.keyboard.press('Meta+P')` |
| Form input testing | Type action | `{"type": "keyboard", "action": "type", "text": "input"}` |
| Testing handler logic | Direct evaluation | `page.evaluate('() => myHandler(event)')` |

**Key Takeaway**: You cannot create trusted keyboard events via JavaScript. Use Playwright's native keyboard API for integration tests, or test handlers directly for unit tests.
