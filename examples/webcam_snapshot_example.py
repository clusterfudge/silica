"""Example demonstrating the webcam snapshot tool.

This example shows how to:
1. Check if webcam capabilities are available
2. Take a snapshot with default settings
3. Take a snapshot with custom parameters
4. Handle errors gracefully

Note: This requires opencv-python to be installed:
    pip install opencv-python
"""

import asyncio
from unittest.mock import MagicMock

from silica.developer.context import AgentContext
from silica.developer.tools.webcam import (
    get_webcam_capabilities,
    webcam_snapshot,
)


async def main():
    """Run webcam snapshot examples."""
    # Create a mock context (in real usage, this would be provided by the agent)
    context = MagicMock(spec=AgentContext)

    print("=" * 70)
    print("Webcam Snapshot Tool Examples")
    print("=" * 70)

    # Example 1: Check capabilities
    print("\n1. Checking webcam capabilities...")
    print("-" * 70)
    capabilities = await get_webcam_capabilities(context)
    print(capabilities)

    if "Not Available" in capabilities:
        print("\n⚠️  Webcam not available. Install OpenCV with:")
        print("    pip install opencv-python")
        return

    # Example 2: Take a basic snapshot
    print("\n2. Taking a basic snapshot (default camera)...")
    print("-" * 70)
    result = await webcam_snapshot(context)

    if isinstance(result, str):
        print(f"Error: {result}")
        return

    # Display metadata
    text_block = result[0]
    print(text_block["text"])

    # Verify image was captured
    image_block = result[1]
    print("\n✓ Image captured successfully!")
    print(f"  Format: {image_block['source']['media_type']}")
    print(f"  Encoding: {image_block['source']['type']}")
    print(f"  Data size: {len(image_block['source']['data'])} characters (base64)")

    # Example 3: Take a snapshot with custom settings
    print("\n3. Taking a snapshot with custom settings...")
    print("-" * 70)
    print("  - Using 5 warmup frames for better quality")
    print("  - Requesting 1280x720 resolution")

    result2 = await webcam_snapshot(context, width=1280, height=720, warmup_frames=5)

    if isinstance(result2, list):
        text_block2 = result2[0]
        print(f"\n{text_block2['text']}")
        print("\n✓ Custom snapshot captured successfully!")

    # Example 4: Try secondary camera (if available)
    print("\n4. Attempting to access secondary camera...")
    print("-" * 70)
    result3 = await webcam_snapshot(context, camera_index=1)

    if isinstance(result3, str):
        print(f"Secondary camera not available: {result3}")
    else:
        print("✓ Secondary camera snapshot captured!")
        print(result3[0]["text"])

    print("\n" + "=" * 70)
    print("Examples complete!")
    print("=" * 70)
    print("\nCheck the .agent-scratchpad directory for saved images.")


if __name__ == "__main__":
    asyncio.run(main())
