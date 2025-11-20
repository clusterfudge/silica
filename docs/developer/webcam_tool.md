# Webcam Snapshot Tool

The webcam snapshot tool allows the agent to capture images from a connected webcam and receive them as properly formatted image messages that can be analyzed by Claude's vision capabilities.

## Tools

### `get_webcam_capabilities`

Check if webcam capture is available in the current environment.

**Parameters:** None

**Returns:** Information about whether OpenCV is installed and a webcam is accessible.

**Example:**
```python
result = await get_webcam_capabilities(context)
# Returns status of OpenCV installation and webcam accessibility
```

### `webcam_snapshot`

Take a picture with the webcam and return a properly formatted image message.

**Parameters:**
- `camera_index` (int, optional): Index of the camera to use (default: 0 for primary webcam)
- `width` (int, optional): Optional width to resize image (maintains aspect ratio if height not provided)
- `height` (int, optional): Optional height to resize image (maintains aspect ratio if width not provided)
- `warmup_frames` (int, optional): Number of frames to capture and discard before taking snapshot (default: 3)

**Returns:** A list containing:
1. A text block with metadata about the capture (camera index, resolution, file size, save location)
2. An image block with the captured image in base64-encoded PNG format

**Example:**
```python
# Take a snapshot with default settings (primary webcam)
result = await webcam_snapshot(context)

# Use a secondary webcam
result = await webcam_snapshot(context, camera_index=1)

# Capture with specific resolution
result = await webcam_snapshot(context, width=1280, height=720)

# Use more warmup frames for better image quality
result = await webcam_snapshot(context, warmup_frames=5)
```

## Image Format

The tool returns images in the proper format for Claude's vision API:

```python
[
    {
        "type": "text",
        "text": "Webcam snapshot captured!\nCamera: 0\nResolution: 640x480\n..."
    },
    {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "<base64-encoded-png-data>"
        }
    }
]
```

This format allows Claude to directly view and analyze the captured image.

## Setup

The webcam tool requires OpenCV to be installed:

```bash
pip install opencv-python
```

Or if using uv:

```bash
uv pip install opencv-python
```

The tool will automatically check if OpenCV is available and provide helpful error messages if it's not installed or if no webcam is detected.

## Implementation Details

### Warmup Frames

Webcams often need a few frames to adjust exposure, focus, and white balance. The `warmup_frames` parameter (default: 3) allows the tool to capture and discard initial frames before taking the actual snapshot. This results in better image quality.

### Image Storage

All captured images are saved to the `.agent-scratchpad` directory with timestamped filenames:
- Format: `webcam_snapshot_YYYYMMDD_HHMMSS.png`
- The directory is automatically created if it doesn't exist
- The directory should be added to `.gitignore` to avoid committing temporary files

### Error Handling

The tool gracefully handles various error conditions:
- OpenCV not installed: Returns installation instructions
- No webcam detected: Returns clear error message
- Camera fails to open: Returns specific error about the camera index
- Frame capture fails: Returns error and ensures camera is released
- Image encoding fails: Returns error and ensures camera is released

The camera is always properly released using a try/finally block, even if errors occur during capture.

## Use Cases

1. **Visual verification**: Allow the agent to see the physical environment
2. **Object detection**: Capture images for analysis and identification
3. **Documentation**: Take pictures to document physical setup or configuration
4. **Debugging**: Capture visual context when troubleshooting hardware or physical issues
5. **Interactive applications**: Enable real-time visual feedback in agent workflows

## Prior Art

This tool follows the same pattern as the `browser_session_screenshot` tool, returning a properly formatted list with both text metadata and image data that Claude can process directly.
