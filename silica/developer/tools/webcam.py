"""Tool for capturing webcam snapshots."""

import base64
from datetime import datetime
from pathlib import Path
from typing import Optional

from silica.developer.context import AgentContext

from .framework import tool


def _ensure_scratchpad() -> Path:
    """Ensure the .agent-scratchpad directory exists and return its path."""
    scratchpad = Path(".agent-scratchpad")
    scratchpad.mkdir(exist_ok=True)
    return scratchpad


async def _check_opencv_available() -> tuple[bool, Optional[str]]:
    """Check if OpenCV is available for webcam capture."""
    try:
        import cv2

        # Try to open default camera to verify it works
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return (
                False,
                "OpenCV is installed but no webcam detected or permission denied",
            )
        cap.release()
        return True, None
    except ImportError:
        return False, (
            "OpenCV is not installed.\nInstall with: pip install opencv-python"
        )
    except Exception as e:
        return False, f"Unexpected error checking OpenCV: {str(e)}"


@tool(group="Webcam")
async def get_webcam_capabilities(context: AgentContext) -> str:
    """Check if webcam capture is available in the current environment.

    Returns information about whether OpenCV is installed and a webcam is accessible.
    """
    capabilities = {
        "opencv_installed": False,
        "webcam_available": False,
        "tools_available": False,
        "details": [],
    }

    # Check OpenCV
    opencv_available, error_msg = await _check_opencv_available()

    if opencv_available:
        capabilities["opencv_installed"] = True
        capabilities["webcam_available"] = True
        capabilities["tools_available"] = True
        capabilities["details"].append("✓ OpenCV installed")
        capabilities["details"].append("✓ Webcam accessible")
        capabilities["details"].append("✓ Webcam snapshot tool available")
    else:
        if "not installed" in error_msg:
            capabilities["details"].append("✗ OpenCV not installed")
        elif "no webcam detected" in error_msg:
            capabilities["opencv_installed"] = True
            capabilities["details"].append("✓ OpenCV installed")
            capabilities["details"].append("✗ No webcam detected or permission denied")
        else:
            capabilities["details"].append(f"✗ OpenCV error: {error_msg}")

    # Build response
    response = ["=== Webcam Tool Capabilities ===\n"]
    response.append(
        f"Webcam Tools: {'Available' if capabilities['tools_available'] else 'Not Available'}\n"
    )
    response.append("\n=== Details ===\n")
    response.extend([f"  {d}\n" for d in capabilities["details"]])

    if not capabilities["tools_available"]:
        response.append("\n=== Setup Instructions ===\n")
        response.append("To enable webcam tools, install OpenCV:\n")
        response.append("  pip install opencv-python\n")

    return "".join(response)


@tool(group="Webcam")
async def webcam_snapshot(
    context: AgentContext,
    camera_index: int = 0,
    width: Optional[int] = None,
    height: Optional[int] = None,
    warmup_frames: int = 3,
) -> list:
    """Take a picture with the webcam and return a properly formatted image message.

    Args:
        camera_index: Index of the camera to use (default: 0 for primary webcam)
        width: Optional width to resize image (maintains aspect ratio if height not provided)
        height: Optional height to resize image (maintains aspect ratio if width not provided)
        warmup_frames: Number of frames to capture and discard before taking snapshot (default: 3)

    Returns:
        List containing text description and image data in proper format for Claude
    """
    # Check if OpenCV is available
    opencv_available, error_msg = await _check_opencv_available()
    if not opencv_available:
        return f"Webcam tool not available:\n{error_msg}"

    import cv2

    scratchpad = _ensure_scratchpad()

    try:
        # Open the camera
        cap = cv2.VideoCapture(camera_index)

        if not cap.isOpened():
            return f"Error: Could not open camera {camera_index}. Check if webcam is connected and accessible."

        try:
            # Set resolution if specified
            if width:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            if height:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

            # Get actual resolution (may differ from requested)
            actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            # Warmup: discard first few frames to let camera adjust
            for _ in range(warmup_frames):
                ret, _ = cap.read()
                if not ret:
                    return "Error: Failed to capture warmup frames from webcam"

            # Capture the actual snapshot
            ret, frame = cap.read()
            if not ret:
                return "Error: Failed to capture image from webcam"

            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"webcam_snapshot_{timestamp}.png"
            filepath = scratchpad / filename

            # Save the image
            cv2.imwrite(str(filepath), frame)

            # Convert to PNG format in memory for base64 encoding
            # This ensures we're sending PNG format regardless of the save
            success, buffer = cv2.imencode(".png", frame)
            if not success:
                return "Error: Failed to encode image as PNG"

            image_data = buffer.tobytes()
            base64_data = base64.b64encode(image_data).decode("utf-8")

            return [
                {
                    "type": "text",
                    "text": (
                        f"Webcam snapshot captured!\n"
                        f"Camera: {camera_index}\n"
                        f"Resolution: {actual_width}x{actual_height}\n"
                        f"Size: {len(image_data)} bytes\n"
                        f"Saved to: {filepath.absolute()}"
                    ),
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64_data,
                    },
                },
            ]

        finally:
            # Always release the camera
            cap.release()

    except Exception as e:
        return f"Error capturing webcam snapshot: {str(e)}"
