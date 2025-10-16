# Browser Tools for Web Development

This document describes the browser automation and screenshot tools available in Silica, which enable agents to visualize and interact with web applications they build.

## Overview

The browser tools solve a critical limitation: agents being "blind" when creating web UIs. These tools provide:

1. **Screenshot capabilities** - Capture visual representations of web pages
2. **Browser automation** - Interact with web applications (click, type, test)
3. **Headless operation** - Runs in headless environments with Playwright

## Tools

### 1. `screenshot_webpage`

Captures a screenshot of a web page, allowing you to see what you've built.

**Parameters:**
- `url` (required): URL to screenshot (local or remote)
- `viewport_width`: Browser viewport width in pixels (default: 1920)
- `viewport_height`: Browser viewport height in pixels (default: 1080)
- `selector`: CSS selector to screenshot specific element only
- `full_page`: If True, captures entire scrollable page (default: False)
- `wait_for`: Wait for selector or "networkidle" before capturing
- `output_format`: Image format - "png" or "jpeg" (default: "png")

**Example Usage:**
```python
# Basic screenshot
screenshot_webpage(context, "http://localhost:8000")

# Specific viewport size
screenshot_webpage(
    context,
    "http://localhost:8000",
    viewport_width=1280,
    viewport_height=720
)

# Screenshot specific element
screenshot_webpage(
    context,
    "http://localhost:8000",
    selector="#main-content"
)

# Wait for element before capturing
screenshot_webpage(
    context,
    "http://localhost:8000",
    wait_for=".loaded"
)

# Full page screenshot
screenshot_webpage(
    context,
    "http://localhost:8000",
    full_page=True
)
```

**Output:**
- Screenshot saved to `.agent-scratchpad/screenshot_TIMESTAMP.png`
- Returns file path and base64-encoded image data
- Includes viewport dimensions and URL

### 2. `browser_interact`

Automates browser interactions to test web applications.

**Parameters:**
- `url` (required): URL to interact with
- `actions` (required): JSON string of actions to perform (see below)
- `viewport_width`: Browser viewport width (default: 1920)
- `viewport_height`: Browser viewport height (default: 1080)
- `capture_screenshots`: Capture screenshots after each action (default: True)
- `capture_console`: Capture console logs (default: True)
- `timeout`: Default timeout for actions in milliseconds (default: 30000)

**Action Types:**

```json
[
  {"type": "click", "selector": "#button-id"},
  {"type": "type", "selector": "#input-field", "text": "user input"},
  {"type": "select", "selector": "#dropdown", "value": "option1"},
  {"type": "hover", "selector": ".menu-item"},
  {"type": "wait", "selector": ".result"},
  {"type": "wait", "ms": 1000},
  {"type": "scroll", "x": 0, "y": 500},
  {"type": "screenshot"},
  {"type": "evaluate", "script": "return document.title"}
]
```

**Example Usage:**
```python
import json

# Test a login form
actions = json.dumps([
    {"type": "type", "selector": "#username", "text": "testuser"},
    {"type": "type", "selector": "#password", "text": "password123"},
    {"type": "click", "selector": "#login-button"},
    {"type": "wait", "selector": ".dashboard"},
    {"type": "evaluate", "script": "return document.title"}
])

result = browser_interact(
    context,
    "http://localhost:8000/login",
    actions
)
```

**Output:**
- List of actions performed with results
- Screenshots saved to `.agent-scratchpad/screenshot_TIMESTAMP_actionN.png`
- Console logs (if enabled)
- JavaScript evaluation results

### 3. `get_browser_capabilities`

Check what browser tools are available in the current environment.

**Parameters:** None

**Example Usage:**
```python
result = get_browser_capabilities(context)
print(result)
```

**Output:**
```
=== Browser Tool Capabilities ===
Browser Tools: Available

=== Details ===
  ✓ Playwright installed and browser ready
  ✓ screenshot_webpage available
  ✓ browser_interact available
```

## Installation

### Standard Installation

Install Playwright for browser automation:

```bash
pip install 'pysilica[browser]'
playwright install chromium
```

Or manually:

```bash
pip install playwright
playwright install chromium
```

### Docker Deployment

Use the Playwright Docker image as a base:

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.40.0

# Install your application
COPY . /app
WORKDIR /app
RUN pip install -e '.[browser]'
```

### System Dependencies

On Linux systems, you may need to install system dependencies:

```bash
playwright install-deps
```

## Architecture

### Playwright-Based

The tools use Playwright for browser automation:
- Launches headless Chromium browser
- Renders pages locally
- Full automation capabilities
- No external dependencies

### Environment Detection

The tools automatically detect if Playwright is available:

```python
# Check at runtime
playwright_available, error = _check_playwright_available()

if not playwright_available:
    return f"Browser tools not available:\n{error}"
```

If Playwright is not installed, tools provide clear installation instructions.

## File Management

All screenshots are saved to `.agent-scratchpad/`:
- This directory is automatically created
- Already in `.gitignore`
- Cleaned up between sessions

**Naming convention:**
- Screenshots: `screenshot_YYYYMMDD_HHMMSS.png`
- Action screenshots: `screenshot_YYYYMMDD_HHMMSS_action1.png`

## Use Cases

### 1. Verifying UI After Development

```python
# After creating a Flask app
screenshot_webpage(context, "http://localhost:5000")
# Review the screenshot to verify layout
```

### 2. Testing Form Submissions

```python
actions = json.dumps([
    {"type": "type", "selector": "#email", "text": "test@example.com"},
    {"type": "type", "selector": "#message", "text": "Hello!"},
    {"type": "click", "selector": "#submit"},
    {"type": "wait", "selector": ".success-message"}
])

result = browser_interact(context, "http://localhost:5000/contact", actions)
# Verify form submission worked
```

### 3. Responsive Design Testing

```python
# Test mobile viewport
screenshot_webpage(
    context,
    "http://localhost:5000",
    viewport_width=375,
    viewport_height=667
)

# Test desktop viewport  
screenshot_webpage(
    context,
    "http://localhost:5000",
    viewport_width=1920,
    viewport_height=1080
)
```

### 4. Debugging JavaScript Errors

```python
actions = json.dumps([
    {"type": "click", "selector": "#trigger-action"},
    {"type": "wait", "ms": 500}
])

result = browser_interact(
    context,
    "http://localhost:5000",
    actions,
    capture_console=True
)
# Check console logs for errors
```

## Troubleshooting

### "Playwright is not installed"

```bash
pip install playwright
playwright install chromium
```

### "Browser binaries are missing"

```bash
playwright install chromium
```

### "Executable doesn't exist" (Linux/Raspberry Pi)

Install system dependencies:
```bash
playwright install-deps
```

### Timeout Errors

Increase the timeout parameter:
```python
browser_interact(context, url, actions, timeout=60000)  # 60 seconds
```

Or add explicit waits:
```json
{"type": "wait", "ms": 5000}
```

### Memory Issues (Resource-Constrained)

Playwright's headless Chromium is lightweight but still requires ~200MB. For very constrained environments (e.g., Raspberry Pi Zero), consider running browser tools on a different machine and accessing via network.

## Security Considerations

1. **Local URLs Only for Sensitive Data**: When testing local development servers, ensure they're not exposed publicly
2. **Screenshot Storage**: Screenshots are stored in `.agent-scratchpad/` - ensure this directory isn't committed to version control
3. **XSS/JavaScript Execution**: The `evaluate` action executes arbitrary JavaScript - only use with trusted content
4. **Browser Isolation**: Each tool invocation runs in an isolated browser instance for security

## Performance Tips

1. **Viewport Size**: Smaller viewports render faster
2. **Network Idle**: Use `wait_for="networkidle"` for dynamic content
3. **Selective Screenshots**: Use `selector` parameter to capture only needed elements
4. **Batch Actions**: Combine multiple actions in one `browser_interact` call
5. **Reuse Sessions**: Tools automatically manage browser lifecycle per call

## Future Enhancements

Potential improvements (not yet implemented):
- Visual regression testing (compare screenshots)
- Accessibility checks (WCAG compliance)
- Performance metrics (Core Web Vitals)
- Network request monitoring
- PDF export
- Video recording of interactions
- Parallel screenshot capture (multiple viewports)

## Related Documentation

- [Tool Framework](./tool_framework.md)
- [Web Tools](./web_tools.md)
- [Sandbox Debug Tool](./sandbox_debug_tool.md)
