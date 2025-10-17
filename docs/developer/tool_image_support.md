# Image Support in Tool Framework

## Overview

The Silica tool framework supports returning images (and other rich content) from tools, allowing Claude to directly view and analyze visual output. This is particularly useful for:

- **Screenshot tools**: Return actual images instead of just descriptions
- **Visualization tools**: Show charts, graphs, diagrams
- **Image processing tools**: Display before/after comparisons
- **Any visual output**: Maps, renders, generated content

## How It Works

### Content Block Format

Tools can now return content in three formats:

#### 1. String (Legacy - Still Supported)
```python
@tool
def simple_tool(context: AgentContext) -> str:
    """Traditional string return."""
    return "This is a simple text response"
```

The framework automatically keeps string responses as-is for backward compatibility.

#### 2. List of Content Blocks (Recommended for Rich Content)
```python
@tool
def image_tool(context: AgentContext) -> list:
    """Return text and image."""
    return [
        {
            "type": "text",
            "text": "Here's the screenshot:"
        },
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64_encoded_image
            }
        }
    ]
```

#### 3. Single Content Block Dict
```python
@tool
def single_block_tool(context: AgentContext) -> dict:
    """Return a single content block."""
    return {
        "type": "text",
        "text": "Single block response"
    }
```

The framework automatically wraps single blocks in a list.

## Content Block Types

### Text Block
```python
{
    "type": "text",
    "text": "Your text content here"
}
```

### Image Block
```python
{
    "type": "image",
    "source": {
        "type": "base64",
        "media_type": "image/png",  # or "image/jpeg", "image/gif", "image/webp"
        "data": "<base64-encoded-image-data>"
    }
}
```

## Complete Example: Screenshot Tool

```python
import base64
from pathlib import Path
from silica.developer.context import AgentContext
from silica.developer.tools.framework import tool

@tool
def screenshot_webpage(
    context: AgentContext,
    url: str,
    viewport_width: int = 1920,
    viewport_height: int = 1080
) -> list:
    """Take a screenshot of a webpage.
    
    Args:
        url: The URL to screenshot
        viewport_width: Browser viewport width in pixels
        viewport_height: Browser viewport height in pixels
    """
    # ... playwright code to capture screenshot ...
    # screenshot saved to filepath
    
    # Read and encode the image
    with open(filepath, "rb") as f:
        image_data = f.read()
        base64_data = base64.b64encode(image_data).decode("utf-8")
    
    # Return both text description and the actual image
    return [
        {
            "type": "text",
            "text": (
                f"Screenshot captured successfully!\n"
                f"URL: {url}\n"
                f"Viewport: {viewport_width}x{viewport_height}\n"
                f"Size: {len(image_data)} bytes"
            )
        },
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64_data
            }
        }
    ]
```

## Multiple Images

Tools can return multiple images in a single response:

```python
@tool
def compare_screenshots(context: AgentContext, url1: str, url2: str) -> list:
    """Compare two webpages side by side."""
    # ... capture both screenshots ...
    
    return [
        {"type": "text", "text": "Comparison of two pages:"},
        {"type": "text", "text": f"\n**Page 1**: {url1}"},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": screenshot1_base64
            }
        },
        {"type": "text", "text": f"\n**Page 2**: {url2}"},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": screenshot2_base64
            }
        }
    ]
```

## Best Practices

### 1. Always Include Text Context
Even when returning images, include text blocks to provide context:

```python
return [
    {"type": "text", "text": "Screenshot of homepage at 1920x1080:"},
    {"type": "image", "source": {...}}
]
```

### 2. Order Matters
Put text descriptions before images for better readability:

```python
# Good
[text_block, image_block, text_block]

# Less readable
[image_block, text_block]
```

### 3. Image Size Considerations
Claude has token limits. For large images, consider:
- Reducing resolution for screenshots
- Using JPEG with compression for photos
- Limiting the number of images per response

### 4. Handle Errors Gracefully
If image capture fails, return a text-only response:

```python
try:
    # ... capture image ...
    return [text_block, image_block]
except Exception as e:
    return f"Error capturing image: {e}"
```

## Framework Implementation Details

The `invoke_tool` function in `silica/developer/tools/framework.py` handles the conversion:

```python
# Check result type and format accordingly
if isinstance(result, str):
    # Legacy string return - keep as-is
    content = result
elif isinstance(result, list):
    # List of content blocks - use directly
    content = result
elif isinstance(result, dict) and "type" in result:
    # Single content block - wrap in list
    content = [result]
else:
    # Unknown format - convert to string
    content = str(result)

return {"type": "tool_result", "tool_use_id": tool_use.id, "content": content}
```

## Backward Compatibility

**All existing tools continue to work without changes.** String returns are still fully supported:

```python
@tool
def old_tool(context: AgentContext) -> str:
    return "This still works perfectly"
```

## Testing

Test your tools with different return formats:

```python
import pytest
from silica.developer.tools.framework import invoke_tool

@pytest.mark.asyncio
async def test_image_return(mock_context):
    """Test tool returning image content."""
    tool_use = MockToolUse("screenshot_tool", {"url": "http://example.com"})
    result = await invoke_tool(mock_context, tool_use, tools=[screenshot_tool])
    
    assert isinstance(result["content"], list)
    assert result["content"][0]["type"] == "text"
    assert result["content"][1]["type"] == "image"
    assert "data" in result["content"][1]["source"]
```

## Supported Media Types

- `image/png` - PNG images (lossless, good for screenshots)
- `image/jpeg` - JPEG images (lossy compression, good for photos)
- `image/gif` - GIF images (animated or static)
- `image/webp` - WebP images (modern format, good compression)

## Size Limits

Claude's API has limits on image size:
- Maximum image size: ~5MB per image (base64 encoded)
- Total message size: Check current API limits
- Consider resizing large screenshots

## Future Extensions

The content block system can be extended to support:
- Document blocks (PDF, etc.)
- Video/audio (if API supports)
- Interactive content
- Structured data visualizations

## Related Documentation

- [Browser Tools](./browser_tools.md) - Using image returns in practice
- [Tool Framework](./tool_framework.md) - General tool development
- [Testing Tools](./testing_tools.md) - Testing strategies
