"""Tests for user tool image support in toolbox.

When user tools return JSON with base64 image data, the toolbox should
convert it to proper Anthropic API image content blocks instead of
treating it as text (which would cause context explosion).
"""

import base64
import json
import pytest
from unittest.mock import MagicMock, patch

from silica.developer.toolbox import Toolbox
from silica.developer.context import AgentContext


class TestUserToolImageSupport:
    """Test image detection and conversion in user tool results."""

    @pytest.fixture
    def mock_context(self, tmp_path):
        """Create a mock context for testing."""
        context = MagicMock(spec=AgentContext)
        context.history_base_dir = tmp_path
        context.user_interface = MagicMock()
        context.sandbox = MagicMock()
        context.sandbox.check_permissions = MagicMock(return_value=True)
        return context

    @pytest.fixture
    def toolbox(self, mock_context):
        """Create a toolbox instance for testing."""
        with patch("silica.developer.toolbox.PermissionsManager"):
            with patch("silica.developer.toolbox.discover_tools", return_value=[]):
                return Toolbox(mock_context, show_warnings=False)

    def test_detect_png_media_type(self, toolbox):
        """Test PNG detection from magic bytes."""
        # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        base64_data = base64.b64encode(png_header).decode("utf-8")

        media_type = toolbox._detect_image_media_type(base64_data)
        assert media_type == "image/png"

    def test_detect_jpeg_media_type(self, toolbox):
        """Test JPEG detection from magic bytes."""
        # JPEG magic bytes: FF D8 FF
        jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 10
        base64_data = base64.b64encode(jpeg_header).decode("utf-8")

        media_type = toolbox._detect_image_media_type(base64_data)
        assert media_type == "image/jpeg"

    def test_detect_gif_media_type(self, toolbox):
        """Test GIF detection from magic bytes."""
        # GIF magic bytes: GIF89a or GIF87a
        gif_header = b"GIF89a" + b"\x00" * 10
        base64_data = base64.b64encode(gif_header).decode("utf-8")

        media_type = toolbox._detect_image_media_type(base64_data)
        assert media_type == "image/gif"

    def test_detect_webp_media_type(self, toolbox):
        """Test WebP detection from magic bytes."""
        # WebP: RIFF....WEBP
        webp_header = b"RIFF\x00\x00\x00\x00WEBP"
        base64_data = base64.b64encode(webp_header).decode("utf-8")

        media_type = toolbox._detect_image_media_type(base64_data)
        assert media_type == "image/webp"

    def test_detect_unknown_defaults_to_png(self, toolbox):
        """Test that unknown formats default to PNG."""
        unknown_data = b"UNKNOWN_FORMAT"
        base64_data = base64.b64encode(unknown_data).decode("utf-8")

        media_type = toolbox._detect_image_media_type(base64_data)
        assert media_type == "image/png"

    def test_process_result_with_base64_image(self, toolbox):
        """Test processing a result with top-level base64 field."""
        # Create a fake PNG image
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        base64_data = base64.b64encode(png_header).decode("utf-8")

        parsed = {
            "success": True,
            "base64": base64_data,
            "dimensions": "800x600",
            "message": "Screenshot captured",
        }

        result = toolbox._process_user_tool_result(parsed)

        # Should return a list of content blocks
        assert isinstance(result, list)
        assert len(result) == 2

        # First block should be text with other fields
        text_block = result[0]
        assert text_block["type"] == "text"
        text_content = json.loads(text_block["text"])
        assert text_content["success"] is True
        assert text_content["dimensions"] == "800x600"
        assert text_content["message"] == "Screenshot captured"
        assert "base64" not in text_content

        # Second block should be the image
        image_block = result[1]
        assert image_block["type"] == "image"
        assert image_block["source"]["type"] == "base64"
        assert image_block["source"]["media_type"] == "image/png"
        assert image_block["source"]["data"] == base64_data

    def test_process_result_with_explicit_media_type(self, toolbox):
        """Test processing a result with explicit media_type field."""
        base64_data = base64.b64encode(b"fake image data").decode("utf-8")

        parsed = {"success": True, "base64": base64_data, "media_type": "image/jpeg"}

        result = toolbox._process_user_tool_result(parsed)

        # Should use the explicit media type
        assert isinstance(result, list)
        image_block = result[-1]
        assert image_block["source"]["media_type"] == "image/jpeg"

    def test_process_result_with_nested_image_object(self, toolbox):
        """Test processing a result with nested image object."""
        base64_data = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("utf-8")

        parsed = {
            "success": True,
            "image": {"base64": base64_data, "media_type": "image/png"},
            "message": "Image captured",
        }

        result = toolbox._process_user_tool_result(parsed)

        # Should return a list of content blocks
        assert isinstance(result, list)
        assert len(result) == 2

        # Text block should not contain the image object
        text_block = result[0]
        text_content = json.loads(text_block["text"])
        assert "image" not in text_content
        assert text_content["success"] is True

        # Image block should have the data
        image_block = result[1]
        assert image_block["type"] == "image"
        assert image_block["source"]["data"] == base64_data

    def test_process_result_without_image(self, toolbox):
        """Test processing a result without any image data."""
        parsed = {
            "success": True,
            "message": "Operation completed",
            "data": {"key": "value"},
        }

        result = toolbox._process_user_tool_result(parsed)

        # Should return a formatted JSON string
        assert isinstance(result, str)
        result_parsed = json.loads(result)
        assert result_parsed == parsed

    def test_process_result_base64_only_image(self, toolbox):
        """Test processing a result with only base64 (no other fields)."""
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        base64_data = base64.b64encode(png_header).decode("utf-8")

        parsed = {"base64": base64_data}

        result = toolbox._process_user_tool_result(parsed)

        # Should return only an image block (no text block since no other fields)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "image"

    @pytest.mark.asyncio
    async def test_invoke_user_tool_with_image(self, toolbox):
        """Test full invocation flow with image result."""
        # Create a mock tool_use object
        tool_use = MagicMock()
        tool_use.name = "screenshot"
        tool_use.id = "test_id_123"
        tool_use.input = {}

        # Create a mock result with image data
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        base64_data = base64.b64encode(png_header).decode("utf-8")
        mock_output = json.dumps(
            {"success": True, "base64": base64_data, "message": "Screenshot captured"}
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = mock_output

        with patch(
            "silica.developer.toolbox.invoke_user_tool", return_value=mock_result
        ):
            result = await toolbox._invoke_user_tool(tool_use)

        # Result should have tool_result type with content blocks
        assert result["type"] == "tool_result"
        assert result["tool_use_id"] == "test_id_123"

        # Content should be a list with text and image blocks
        content = result["content"]
        assert isinstance(content, list)
        assert len(content) == 2

        # Verify the image block is correct
        image_block = content[-1]
        assert image_block["type"] == "image"
        assert image_block["source"]["data"] == base64_data

    @pytest.mark.asyncio
    async def test_invoke_user_tool_without_image(self, toolbox):
        """Test invocation flow without image (backwards compatibility)."""
        tool_use = MagicMock()
        tool_use.name = "hello_world"
        tool_use.id = "test_id_456"
        tool_use.input = {"name": "World"}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = json.dumps({"success": True, "greeting": "Hello, World!"})

        with patch(
            "silica.developer.toolbox.invoke_user_tool", return_value=mock_result
        ):
            result = await toolbox._invoke_user_tool(tool_use)

        # Content should be a formatted JSON string (backwards compatible)
        assert result["type"] == "tool_result"
        content = result["content"]
        assert isinstance(content, str)
        parsed = json.loads(content)
        assert parsed["greeting"] == "Hello, World!"

    @pytest.mark.asyncio
    async def test_invoke_user_tool_with_error(self, toolbox):
        """Test invocation flow with tool error."""
        tool_use = MagicMock()
        tool_use.name = "failing_tool"
        tool_use.id = "test_id_789"
        tool_use.input = {}

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.exit_code = 1
        mock_result.output = "Some output"
        mock_result.error = "Error occurred"

        with patch(
            "silica.developer.toolbox.invoke_user_tool", return_value=mock_result
        ):
            result = await toolbox._invoke_user_tool(tool_use)

        # Error result should be text content
        assert result["type"] == "tool_result"
        content = result["content"]
        assert isinstance(content, str)
        assert "Tool execution failed" in content
        assert "Error occurred" in content


class TestImageDetectionEdgeCases:
    """Test edge cases in image detection."""

    @pytest.fixture
    def toolbox(self, tmp_path):
        """Create a toolbox instance for testing."""
        context = MagicMock(spec=AgentContext)
        context.history_base_dir = tmp_path
        context.user_interface = MagicMock()
        context.sandbox = MagicMock()

        with patch("silica.developer.toolbox.PermissionsManager"):
            with patch("silica.developer.toolbox.discover_tools", return_value=[]):
                return Toolbox(context, show_warnings=False)

    def test_invalid_base64_defaults_to_png(self, toolbox):
        """Test that invalid base64 data defaults to PNG."""
        # Invalid base64 that will fail to decode
        result = toolbox._detect_image_media_type("not-valid-base64!!!")
        assert result == "image/png"

    def test_empty_base64_defaults_to_png(self, toolbox):
        """Test that empty base64 data defaults to PNG."""
        result = toolbox._detect_image_media_type("")
        assert result == "image/png"

    def test_non_string_base64_in_result(self, toolbox):
        """Test that non-string base64 values are ignored."""
        parsed = {
            "success": True,
            "base64": 12345,  # Not a string
            "message": "Test",
        }

        result = toolbox._process_user_tool_result(parsed)

        # Should return as JSON string (no image conversion)
        assert isinstance(result, str)

    def test_nested_image_without_base64(self, toolbox):
        """Test nested image object without base64 field."""
        parsed = {
            "success": True,
            "image": {
                "url": "https://example.com/image.png"  # URL instead of base64
            },
        }

        result = toolbox._process_user_tool_result(parsed)

        # Should return as JSON string (no image conversion)
        assert isinstance(result, str)
