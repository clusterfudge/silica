#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts", "anthropic"]
# ///

"""Read an image file and return it as base64 for viewing.

This tool allows viewing existing image files by converting them to base64.
Useful for viewing screenshots taken by other tools or processes.

Metadata:
    category: utility
    tags: image, view, base64
    creator_persona: assistant
    created: 2025-01-24
    long_running: false
"""

import subprocess
import sys
import base64
import json
from pathlib import Path

import cyclopts
import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema

app = cyclopts.App()

MAX_IMAGE_TOKENS = 25000


def count_image_tokens(image_base64: str, media_type: str = "image/png") -> int | None:
    """Count tokens for an image using Anthropic's token counting API."""
    try:
        client = anthropic.Anthropic()
        response = client.messages.count_tokens(
            model="claude-sonnet-4-5",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        }
                    },
                    {
                        "type": "text",
                        "text": "Describe this image"
                    }
                ]
            }]
        )
        return max(0, response.input_tokens - 5)
    except Exception:
        return None


def get_image_dimensions(image_path: Path) -> tuple[int, int] | None:
    """Get image dimensions using sips (macOS built-in)."""
    try:
        result = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(image_path)],
            capture_output=True, text=True
        )
        width = height = None
        for line in result.stdout.strip().split('\n'):
            if 'pixelWidth' in line:
                width = int(line.split(':')[1].strip())
            elif 'pixelHeight' in line:
                height = int(line.split(':')[1].strip())
        if width and height:
            return (width, height)
    except Exception:
        pass
    return None


def resize_image(image_path: Path, max_dimension: int) -> tuple[Path, tuple[int, int] | None]:
    """Resize image to fit within max_dimension, returns new path and dimensions."""
    import tempfile
    import shutil
    
    dimensions = get_image_dimensions(image_path)
    if not dimensions:
        return image_path, None
    
    orig_width, orig_height = dimensions
    max_orig = max(orig_width, orig_height)
    
    if max_orig <= max_dimension:
        return image_path, dimensions
    
    # Calculate new dimensions
    scale = max_dimension / max_orig
    new_width = int(orig_width * scale)
    new_height = int(orig_height * scale)
    
    # Create temp file and resize
    suffix = image_path.suffix or ".png"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    
    shutil.copy(image_path, tmp_path)
    subprocess.run(
        ["sips", "-z", str(new_height), str(new_width), str(tmp_path)],
        capture_output=True, text=True
    )
    
    return tmp_path, (new_width, new_height)


@app.default
def main(
    path: str = "",
    max_dimension: int | None = None,
    *,
    toolspec: bool = False,
    authorize: bool = False,
):
    """Read an image file and return as base64 for viewing.
    
    Args:
        path: Path to the image file to read.
        max_dimension: Scale image so largest dimension is at most this many pixels.
    """
    if toolspec:
        print(json.dumps(generate_schema(main, "read_image")))
        return

    if authorize:
        print(json.dumps({"success": True, "message": "No authorization needed"}))
        return

    if not path:
        print(json.dumps({"success": False, "error": "path is required"}))
        return

    image_path = Path(path).expanduser()
    
    if not image_path.exists():
        print(json.dumps({"success": False, "error": f"File not found: {path}"}))
        return
    
    # Determine media type from extension
    suffix = image_path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(suffix, "image/png")
    
    response = {"success": True, "path": str(image_path)}
    
    # Get original dimensions
    orig_dimensions = get_image_dimensions(image_path)
    if orig_dimensions:
        response["original_dimensions"] = f"{orig_dimensions[0]}x{orig_dimensions[1]}"
    
    # Resize if needed
    working_path = image_path
    if max_dimension and max_dimension > 0:
        working_path, new_dims = resize_image(image_path, max_dimension)
        if new_dims and working_path != image_path:
            response["scaled_dimensions"] = f"{new_dims[0]}x{new_dims[1]}"
            response["scaled"] = True
    
    # Read and encode
    with open(working_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")
    
    # Count tokens
    token_count = count_image_tokens(image_base64, media_type)
    if token_count is not None:
        response["input_tokens"] = token_count
        
        if token_count > MAX_IMAGE_TOKENS:
            # Clean up temp file if we created one
            if working_path != image_path:
                try:
                    working_path.unlink()
                except Exception:
                    pass
            print(json.dumps({
                "success": False,
                "error": f"Image is too large ({token_count:,} tokens, max {MAX_IMAGE_TOKENS:,}). "
                         f"Use max_dimension parameter to scale down."
            }))
            return
    
    response["base64"] = image_base64
    response["media_type"] = media_type
    
    # Clean up temp file if we created one
    if working_path != image_path:
        try:
            working_path.unlink()
        except Exception:
            pass
    
    print(json.dumps(response))


if __name__ == "__main__":
    app()
