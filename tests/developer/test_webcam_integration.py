"""Integration tests for webcam tool (requires actual webcam)."""

import base64
from pathlib import Path

import pytest

from silica.developer.context import AgentContext
from silica.developer.tools.webcam import (
    get_webcam_capabilities,
    webcam_snapshot,
)


@pytest.fixture
def mock_context():
    """Create a minimal AgentContext for testing."""
    from unittest.mock import MagicMock

    context = MagicMock(spec=AgentContext)
    return context


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_webcam_capabilities_real(mock_context):
    """Test get_webcam_capabilities with actual system (integration test)."""
    result = await get_webcam_capabilities(mock_context)

    # Should return a string with status information
    assert isinstance(result, str)
    assert "Webcam Tool" in result or "webcam" in result.lower()

    # Will show either available or not available depending on system
    print("\n" + result)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webcam_snapshot_real(mock_context):
    """Test webcam_snapshot with actual webcam (integration test).

    This test will be skipped if no webcam is available.
    """
    # First check if webcam is available
    capabilities = await get_webcam_capabilities(mock_context)
    if "Not Available" in capabilities:
        pytest.skip("No webcam available for integration test")

    result = await webcam_snapshot(mock_context)

    # If OpenCV is not installed, we get an error string
    if isinstance(result, str):
        assert "not available" in result.lower() or "error" in result.lower()
        pytest.skip(f"Webcam not functional: {result}")
        return

    # If successful, should return list with text and image
    assert isinstance(result, list)
    assert len(result) == 2

    # Check text block
    text_block = result[0]
    assert text_block["type"] == "text"
    assert "Webcam snapshot captured!" in text_block["text"]
    assert "Camera:" in text_block["text"]
    assert "Resolution:" in text_block["text"]

    # Check image block
    image_block = result[1]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"

    # Verify base64 data is valid PNG
    base64_data = image_block["source"]["data"]
    decoded = base64.b64decode(base64_data)
    assert decoded.startswith(b"\x89PNG\r\n\x1a\n"), "Not a valid PNG image"

    # Verify file was saved
    scratchpad = Path(".agent-scratchpad")
    assert scratchpad.exists()

    # Find the most recent snapshot file
    snapshot_files = list(scratchpad.glob("webcam_snapshot_*.png"))
    assert len(snapshot_files) > 0, "No snapshot file was created"

    print("\n✓ Webcam snapshot successful!")
    print(f"  Resolution: {text_block['text'].split('Resolution: ')[1].split()[0]}")
    print(f"  Image size: {len(decoded)} bytes")
    print(f"  Saved to: {snapshot_files[-1]}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webcam_snapshot_multiple_cameras(mock_context):
    """Test accessing different camera indices (integration test)."""
    # Try camera 0 (should work if any camera is available)
    result = await webcam_snapshot(mock_context, camera_index=0)

    if isinstance(result, str) and "Could not open camera" not in result:
        # If it's an error about OpenCV not available, skip
        if "not available" in result.lower():
            pytest.skip(f"Webcam not functional: {result}")

    # If camera 0 works, result should be a list
    if isinstance(result, list):
        print("\n✓ Camera 0 works")

        # Try camera 1 (may or may not exist)
        result2 = await webcam_snapshot(mock_context, camera_index=1)
        if isinstance(result2, list):
            print("✓ Camera 1 also available")
        else:
            print(f"✗ Camera 1 not available: {result2}")
