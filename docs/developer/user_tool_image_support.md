# User Tool Image Support

User tools can now return image data that will be properly converted to Anthropic API image content blocks, preventing context explosion from base64 text tokenization.

## The Problem

When a user tool (like `screenshot`) returns base64-encoded image data as JSON:

```json
{
    "success": true,
    "base64": "iVBORw0KGgo...",
    "message": "Screenshot captured"
}
```

Previously, this entire JSON (including the ~500KB+ base64 string) would be treated as text and tokenized, potentially consuming 100K+ tokens and exploding the context window.

## The Solution

The Silica framework now automatically detects base64 image data in user tool results and converts it to proper Anthropic API image content blocks:

```json
[
    {
        "type": "text",
        "text": "{\"success\": true, \"message\": \"Screenshot captured\"}"
    },
    {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "iVBORw0KGgo..."
        }
    }
]
```

This allows Claude to actually "see" the image instead of just seeing a wall of base64 characters.

## Supported Patterns

### Pattern 1: Top-level base64 field

```json
{
    "success": true,
    "base64": "iVBORw0KGgo...",
    "media_type": "image/png",  // optional
    "message": "Screenshot captured"
}
```

### Pattern 2: Nested image object

```json
{
    "success": true,
    "image": {
        "base64": "iVBORw0KGgo...",
        "media_type": "image/png"  // optional
    },
    "message": "Image captured"
}
```

## Media Type Detection

If `media_type` is not explicitly provided, the framework will auto-detect it from the image's magic bytes:

| Format | Magic Bytes | Detected Type |
|--------|------------|---------------|
| PNG | `89 50 4E 47` | `image/png` |
| JPEG | `FF D8 FF` | `image/jpeg` |
| GIF | `47 49 46 38` | `image/gif` |
| WebP | `RIFF...WEBP` | `image/webp` |

Unknown formats default to `image/png`.

## Writing Image-Returning Tools

To create a user tool that returns images:

```python
#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts"]
# ///

import base64
import json
from pathlib import Path

import cyclopts

app = cyclopts.App()


@app.default
def capture_image(output: str = "", *, toolspec: bool = False):
    """Capture and return an image.
    
    Args:
        output: Optional file path to save the image
    """
    if toolspec:
        # Generate tool specification
        from _silica_toolspec import generate_schema
        print(json.dumps(generate_schema(capture_image, "capture_image")))
        return
    
    # Capture or generate image
    image_data = b'\x89PNG\r\n\x1a\n...'  # Your image bytes
    
    if output:
        # Save to file
        Path(output).write_bytes(image_data)
        print(json.dumps({
            "success": True,
            "path": output,
            "message": "Image saved"
        }))
    else:
        # Return base64 for Claude to see
        print(json.dumps({
            "success": True,
            "base64": base64.b64encode(image_data).decode("utf-8"),
            "media_type": "image/png",  # Optional but recommended
            "message": "Image captured"
        }))


if __name__ == "__main__":
    app()
```

## Backwards Compatibility

This change is fully backwards compatible:

1. **Tools without images**: Results without `base64` fields are returned as formatted JSON strings, exactly as before.

2. **Built-in tools**: Built-in tools that return images (like `browser_session_screenshot`) already use the content block format directly.

3. **Explicit media types**: If you provide `media_type`, it will be used. Otherwise, auto-detection kicks in.

## Implementation Details

The image detection and conversion happens in `Toolbox._process_user_tool_result()`:

1. Parse the JSON output from the user tool
2. Check for `base64` field (top-level or nested in `image` object)
3. If found, extract the base64 data and detect/use media type
4. Build content blocks: text block (for other fields) + image block
5. Return the content blocks to be sent to the API

This ensures that when Claude receives the tool result, it sees the image as a proper image content block, not as text.
