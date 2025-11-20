"""Tests for webcam snapshot tool."""

import base64
from unittest.mock import MagicMock, patch

import pytest

from silica.developer.context import AgentContext
from silica.developer.tools.webcam import (
    get_webcam_capabilities,
    webcam_snapshot,
    _check_opencv_available,
)


@pytest.fixture
def mock_context():
    """Create a mock AgentContext."""
    context = MagicMock(spec=AgentContext)
    return context


@pytest.mark.asyncio
async def test_check_opencv_available_not_installed():
    """Test _check_opencv_available when OpenCV is not installed."""
    # Mock the import to fail
    with patch.dict("sys.modules", {"cv2": None}):
        with patch(
            "builtins.__import__", side_effect=ImportError("No module named 'cv2'")
        ):
            available, error_msg = await _check_opencv_available()
            assert available is False
            assert "not installed" in error_msg.lower()


@pytest.mark.asyncio
async def test_get_webcam_capabilities_not_available(mock_context):
    """Test get_webcam_capabilities when OpenCV is not available."""
    with patch(
        "silica.developer.tools.webcam._check_opencv_available",
        return_value=(
            False,
            "OpenCV is not installed.\nInstall with: pip install opencv-python",
        ),
    ):
        result = await get_webcam_capabilities(mock_context)

        assert "Not Available" in result
        assert "OpenCV not installed" in result
        assert "pip install opencv-python" in result


@pytest.mark.asyncio
async def test_get_webcam_capabilities_available(mock_context):
    """Test get_webcam_capabilities when OpenCV and webcam are available."""
    with patch(
        "silica.developer.tools.webcam._check_opencv_available",
        return_value=(True, None),
    ):
        result = await get_webcam_capabilities(mock_context)

        assert "Available" in result
        assert "✓ OpenCV installed" in result
        assert "✓ Webcam accessible" in result
        assert "✓ Webcam snapshot tool available" in result


@pytest.mark.asyncio
async def test_webcam_snapshot_opencv_not_available(mock_context):
    """Test webcam_snapshot when OpenCV is not available."""
    with patch(
        "silica.developer.tools.webcam._check_opencv_available",
        return_value=(
            False,
            "OpenCV is not installed.\nInstall with: pip install opencv-python",
        ),
    ):
        result = await webcam_snapshot(mock_context)

        assert isinstance(result, str)
        assert "not available" in result.lower()
        assert "opencv" in result.lower()


@pytest.mark.asyncio
async def test_webcam_snapshot_success(mock_context, tmp_path):
    """Test successful webcam snapshot capture."""
    # Create mock frame data (simulate raw image bytes)
    mock_frame_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    # Mock cv2 module
    mock_cv2 = MagicMock()
    mock_cap = MagicMock()

    # Configure the mock capture device
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {
        3: 640,  # CAP_PROP_FRAME_WIDTH
        4: 480,  # CAP_PROP_FRAME_HEIGHT
    }.get(prop, 0)
    mock_cap.read.return_value = (True, "mock_frame")

    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cv2.CAP_PROP_FRAME_WIDTH = 3
    mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

    # Mock imencode to return success and a buffer
    mock_buffer = MagicMock()
    mock_buffer.tobytes.return_value = mock_frame_data
    mock_cv2.imencode.return_value = (True, mock_buffer)
    mock_cv2.imwrite.return_value = True

    with patch(
        "silica.developer.tools.webcam._check_opencv_available",
        return_value=(True, None),
    ):
        # Need to import cv2 in the webcam module context
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("silica.developer.tools.webcam.Path") as mock_path_class:
                # Setup mock path
                mock_scratchpad = MagicMock()
                mock_filepath = MagicMock()
                mock_filepath.absolute.return_value = "/path/to/snapshot.png"
                mock_scratchpad.__truediv__.return_value = mock_filepath
                mock_path_class.return_value = mock_scratchpad
                mock_scratchpad.mkdir = MagicMock()

                result = await webcam_snapshot(mock_context)

                # Verify result structure
                assert isinstance(result, list)
                assert len(result) == 2

                # Check text message
                text_block = result[0]
                assert text_block["type"] == "text"
                assert "Webcam snapshot captured!" in text_block["text"]
                assert "Camera: 0" in text_block["text"]
                assert "Resolution: 640x480" in text_block["text"]

                # Check image block
                image_block = result[1]
                assert image_block["type"] == "image"
                assert image_block["source"]["type"] == "base64"
                assert image_block["source"]["media_type"] == "image/png"
                assert "data" in image_block["source"]

                # Verify base64 data is valid
                base64_data = image_block["source"]["data"]
                decoded = base64.b64decode(base64_data)
                assert len(decoded) > 0
                assert decoded == mock_frame_data

                # Verify camera was opened and released
                mock_cv2.VideoCapture.assert_called_once_with(0)
                mock_cap.release.assert_called_once()


@pytest.mark.asyncio
async def test_webcam_snapshot_camera_not_opened(mock_context):
    """Test webcam_snapshot when camera fails to open."""
    mock_cv2 = MagicMock()
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = False
    mock_cv2.VideoCapture.return_value = mock_cap

    with patch(
        "silica.developer.tools.webcam._check_opencv_available",
        return_value=(True, None),
    ):
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            result = await webcam_snapshot(mock_context)

            assert isinstance(result, str)
            assert "Error" in result
            assert "Could not open camera" in result
            mock_cap.release.assert_not_called()


@pytest.mark.asyncio
async def test_webcam_snapshot_read_failure(mock_context):
    """Test webcam_snapshot when frame capture fails."""
    mock_cv2 = MagicMock()
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (False, None)
    mock_cv2.VideoCapture.return_value = mock_cap

    with patch(
        "silica.developer.tools.webcam._check_opencv_available",
        return_value=(True, None),
    ):
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("silica.developer.tools.webcam.Path"):
                result = await webcam_snapshot(mock_context)

                assert isinstance(result, str)
                assert "Error" in result
                assert "Failed to capture" in result
                # Camera should still be released
                mock_cap.release.assert_called_once()


@pytest.mark.asyncio
async def test_webcam_snapshot_with_custom_camera_index(mock_context):
    """Test webcam_snapshot with custom camera index."""
    mock_frame_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    mock_cv2 = MagicMock()
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {3: 640, 4: 480}.get(prop, 0)
    mock_cap.read.return_value = (True, "mock_frame")
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cv2.CAP_PROP_FRAME_WIDTH = 3
    mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

    mock_buffer = MagicMock()
    mock_buffer.tobytes.return_value = mock_frame_data
    mock_cv2.imencode.return_value = (True, mock_buffer)
    mock_cv2.imwrite.return_value = True

    with patch(
        "silica.developer.tools.webcam._check_opencv_available",
        return_value=(True, None),
    ):
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("silica.developer.tools.webcam.Path"):
                result = await webcam_snapshot(mock_context, camera_index=1)

                # Verify custom camera index was used
                mock_cv2.VideoCapture.assert_called_once_with(1)
                assert isinstance(result, list)
                assert "Camera: 1" in result[0]["text"]


@pytest.mark.asyncio
async def test_webcam_snapshot_with_resolution(mock_context):
    """Test webcam_snapshot with custom resolution."""
    mock_frame_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    mock_cv2 = MagicMock()
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {3: 1280, 4: 720}.get(prop, 0)
    mock_cap.read.return_value = (True, "mock_frame")
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cv2.CAP_PROP_FRAME_WIDTH = 3
    mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

    mock_buffer = MagicMock()
    mock_buffer.tobytes.return_value = mock_frame_data
    mock_cv2.imencode.return_value = (True, mock_buffer)
    mock_cv2.imwrite.return_value = True

    with patch(
        "silica.developer.tools.webcam._check_opencv_available",
        return_value=(True, None),
    ):
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("silica.developer.tools.webcam.Path"):
                result = await webcam_snapshot(mock_context, width=1280, height=720)

                # Verify resolution was set
                assert mock_cap.set.call_count >= 2
                assert isinstance(result, list)
                assert "Resolution: 1280x720" in result[0]["text"]


@pytest.mark.asyncio
async def test_webcam_snapshot_warmup_frames(mock_context):
    """Test that warmup frames are captured and discarded."""
    mock_frame_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    mock_cv2 = MagicMock()
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {3: 640, 4: 480}.get(prop, 0)
    mock_cap.read.return_value = (True, "mock_frame")
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cv2.CAP_PROP_FRAME_WIDTH = 3
    mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

    mock_buffer = MagicMock()
    mock_buffer.tobytes.return_value = mock_frame_data
    mock_cv2.imencode.return_value = (True, mock_buffer)
    mock_cv2.imwrite.return_value = True

    with patch(
        "silica.developer.tools.webcam._check_opencv_available",
        return_value=(True, None),
    ):
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("silica.developer.tools.webcam.Path"):
                result = await webcam_snapshot(mock_context, warmup_frames=5)

                # Verify read was called: 5 warmup frames + 1 actual snapshot = 6 times
                assert mock_cap.read.call_count == 6
                assert isinstance(result, list)


@pytest.mark.asyncio
async def test_webcam_snapshot_encode_failure(mock_context):
    """Test webcam_snapshot when image encoding fails."""
    mock_cv2 = MagicMock()
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {3: 640, 4: 480}.get(prop, 0)
    mock_cap.read.return_value = (True, "mock_frame")
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cv2.CAP_PROP_FRAME_WIDTH = 3
    mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
    mock_cv2.imwrite.return_value = True

    # Mock imencode to fail
    mock_cv2.imencode.return_value = (False, None)

    with patch(
        "silica.developer.tools.webcam._check_opencv_available",
        return_value=(True, None),
    ):
        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            with patch("silica.developer.tools.webcam.Path"):
                result = await webcam_snapshot(mock_context)

                assert isinstance(result, str)
                assert "Error" in result
                assert "Failed to encode" in result
                # Camera should still be released
                mock_cap.release.assert_called_once()
