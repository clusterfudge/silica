"""Tests for image content block support in tool framework."""

import pytest
from unittest.mock import Mock
from silica.developer.context import AgentContext
from silica.developer.tools.framework import tool, invoke_tool


class MockToolUse:
    """Mock tool_use object for testing."""

    def __init__(self, name, input_data, tool_id="test_id"):
        self.name = name
        self.input = input_data
        self.id = tool_id


@pytest.fixture
def mock_context():
    """Create a mock AgentContext."""
    return Mock(spec=AgentContext)


class TestImageContentBlockSupport:
    """Tests for returning image content blocks from tools."""

    @pytest.mark.asyncio
    async def test_string_return_wrapped_in_text_block(self, mock_context):
        """Test that string returns are still supported (backward compatibility)."""

        @tool
        def string_tool(context: AgentContext, message: str) -> str:
            """A tool that returns a string."""
            return f"Echo: {message}"

        tool_use = MockToolUse("string_tool", {"message": "hello"})
        result = await invoke_tool(mock_context, tool_use, tools=[string_tool])

        assert result["type"] == "tool_result"
        assert result["tool_use_id"] == "test_id"
        # String return should be kept as-is for backward compatibility
        assert result["content"] == "Echo: hello"

    @pytest.mark.asyncio
    async def test_list_content_blocks_returned_directly(self, mock_context):
        """Test that list of content blocks is returned directly."""

        @tool
        def image_tool(context: AgentContext) -> list:
            """A tool that returns image content blocks."""
            return [
                {"type": "text", "text": "Here's an image:"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "fake_base64_data",
                    },
                },
            ]

        tool_use = MockToolUse("image_tool", {})
        result = await invoke_tool(mock_context, tool_use, tools=[image_tool])

        assert result["type"] == "tool_result"
        assert result["tool_use_id"] == "test_id"
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 2
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "image"
        assert result["content"][1]["source"]["data"] == "fake_base64_data"

    @pytest.mark.asyncio
    async def test_single_content_block_wrapped_in_list(self, mock_context):
        """Test that single content block dict is wrapped in a list."""

        @tool
        def single_block_tool(context: AgentContext) -> dict:
            """A tool that returns a single content block."""
            return {"type": "text", "text": "Single block"}

        tool_use = MockToolUse("single_block_tool", {})
        result = await invoke_tool(mock_context, tool_use, tools=[single_block_tool])

        assert result["type"] == "tool_result"
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Single block"

    @pytest.mark.asyncio
    async def test_mixed_text_and_image_blocks(self, mock_context):
        """Test tool returning both text and image blocks."""

        @tool
        def mixed_tool(context: AgentContext) -> list:
            """A tool that returns mixed content."""
            return [
                {"type": "text", "text": "Screenshot captured:"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "screenshot_data",
                    },
                },
                {"type": "text", "text": "Analysis complete."},
            ]

        tool_use = MockToolUse("mixed_tool", {})
        result = await invoke_tool(mock_context, tool_use, tools=[mixed_tool])

        assert isinstance(result["content"], list)
        assert len(result["content"]) == 3
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "image"
        assert result["content"][2]["type"] == "text"

    @pytest.mark.asyncio
    async def test_unknown_format_converted_to_string(self, mock_context):
        """Test that unknown return formats are converted to string."""

        @tool
        def weird_tool(context: AgentContext) -> int:
            """A tool that returns an int."""
            return 42

        tool_use = MockToolUse("weird_tool", {})
        result = await invoke_tool(mock_context, tool_use, tools=[weird_tool])

        assert result["content"] == "42"

    @pytest.mark.asyncio
    async def test_multiple_images_in_content(self, mock_context):
        """Test tool returning multiple images."""

        @tool
        def multi_image_tool(context: AgentContext) -> list:
            """A tool that returns multiple images."""
            return [
                {"type": "text", "text": "Before and after:"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "before_image",
                    },
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "after_image",
                    },
                },
            ]

        tool_use = MockToolUse("multi_image_tool", {})
        result = await invoke_tool(mock_context, tool_use, tools=[multi_image_tool])

        assert isinstance(result["content"], list)
        assert len(result["content"]) == 3
        images = [block for block in result["content"] if block["type"] == "image"]
        assert len(images) == 2
        assert images[0]["source"]["data"] == "before_image"
        assert images[1]["source"]["data"] == "after_image"
