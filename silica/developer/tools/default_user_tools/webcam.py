#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts", "opencv-python"]
# ///

"""Webcam capture tool for taking snapshots.

Captures images from webcam and saves them to .agent-scratchpad directory.
Returns base64-encoded image data for Claude to analyze.

Metadata:
    category: hardware
    tags: webcam, camera, image, capture
    creator_persona: system
    created: 2025-01-13
    long_running: false
"""

import base64
import json
import sys
from datetime import datetime
from pathlib import Path

import cyclopts

sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema

app = cyclopts.App()


def _ensure_scratchpad() -> Path:
    """Ensure the .agent-scratchpad directory exists."""
    scratchpad = Path(".agent-scratchpad")
    scratchpad.mkdir(exist_ok=True)
    return scratchpad


def _check_opencv() -> tuple[bool, str | None]:
    """Check if OpenCV and webcam are available."""
    try:
        import cv2

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return False, "No webcam detected or permission denied"
        cap.release()
        return True, None
    except ImportError:
        return False, "OpenCV not installed"
    except Exception as e:
        return False, str(e)


@app.command()
def capabilities(
    *,
    toolspec: bool = False,
):
    """Check if webcam capture is available in the current environment.

    Returns information about whether OpenCV is installed and a webcam is accessible.
    """
    if toolspec:
        print(json.dumps(generate_schema(capabilities, "get_webcam_capabilities")))
        return

    available, error = _check_opencv()

    result = {
        "opencv_installed": error != "OpenCV not installed",
        "webcam_available": available,
        "tools_available": available,
        "details": [],
    }

    if available:
        result["details"] = [
            "✓ OpenCV installed",
            "✓ Webcam accessible",
            "✓ Webcam snapshot tool available",
        ]
    else:
        result["details"].append(f"✗ {error}")

    print(json.dumps(result))


@app.command()
def snapshot(
    camera_index: int = 0,
    width: int = 0,
    height: int = 0,
    warmup_frames: int = 3,
    *,
    toolspec: bool = False,
):
    """Take a picture with the webcam.

    Args:
        camera_index: Index of the camera to use (default: 0 for primary webcam)
        width: Optional width to resize image (0 = no resize)
        height: Optional height to resize image (0 = no resize)
        warmup_frames: Number of frames to capture and discard before taking snapshot (default: 3)
    """
    if toolspec:
        print(json.dumps(generate_schema(snapshot, "webcam_snapshot")))
        return

    available, error = _check_opencv()
    if not available:
        print(json.dumps({"success": False, "error": error}))
        return

    import cv2

    scratchpad = _ensure_scratchpad()

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(
            json.dumps(
                {"success": False, "error": f"Could not open camera {camera_index}"}
            )
        )
        return

    try:
        if width > 0:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height > 0:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Warmup frames
        for _ in range(warmup_frames):
            ret, _ = cap.read()
            if not ret:
                print(
                    json.dumps(
                        {"success": False, "error": "Failed to capture warmup frames"}
                    )
                )
                return

        # Capture
        ret, frame = cap.read()
        if not ret:
            print(json.dumps({"success": False, "error": "Failed to capture image"}))
            return

        # Save and encode
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"webcam_snapshot_{timestamp}.png"
        filepath = scratchpad / filename
        cv2.imwrite(str(filepath), frame)

        success, buffer = cv2.imencode(".png", frame)
        if not success:
            print(json.dumps({"success": False, "error": "Failed to encode image"}))
            return

        image_data = buffer.tobytes()
        base64_data = base64.b64encode(image_data).decode("utf-8")

        print(
            json.dumps(
                {
                    "success": True,
                    "camera_index": camera_index,
                    "resolution": f"{actual_width}x{actual_height}",
                    "size_bytes": len(image_data),
                    "saved_to": str(filepath.absolute()),
                    "image_base64": base64_data,
                    "media_type": "image/png",
                }
            )
        )

    finally:
        cap.release()


@app.default
def main(*, toolspec: bool = False):
    """Webcam tools for capturing images."""
    if toolspec:
        specs = [
            generate_schema(capabilities, "get_webcam_capabilities"),
            generate_schema(snapshot, "webcam_snapshot"),
        ]
        print(json.dumps(specs))
        return

    print("Use 'capabilities' or 'snapshot' subcommands. Run with --help for details.")


if __name__ == "__main__":
    app()
