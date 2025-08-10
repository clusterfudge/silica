from unittest.mock import MagicMock
from silica.developer.tools.framework import invoke_tool
from silica.developer.toolbox import Toolbox


async def test_unknown_tool_handled_gracefully():
    """Test that the toolbox handles unknown tools gracefully"""
    # Create a context mock
    context = MagicMock()

    # Create a toolbox with no tools
    toolbox = Toolbox(context, [])

    # Create a tool specification for an unknown tool
    unknown_tool = MagicMock()
    unknown_tool.name = "unknown_tool"
    unknown_tool.id = "tu_123"
    unknown_tool.input = {"param": "value"}
    unknown_tool.type = "tool_use"

    # Try to execute the unknown tool
    result = await toolbox.invoke_agent_tool(unknown_tool)

    # Check that the result indicates an unknown function error
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "tu_123"
    assert "Unknown function" in result["content"]
    assert "unknown_tool" in result["content"]


async def test_malformed_tool_spec_handled_gracefully():
    """Test that the toolbox handles malformed tool specifications gracefully"""
    # Create a context mock
    context = MagicMock()

    # Create a toolbox with no tools
    toolbox = Toolbox(context, [])

    # Create a malformed tool mock that will raise AttributeError for 'name' and 'input'
    class MalformedTool:
        type = "tool_use"
        id = "tu_456"

        def __getattribute__(self, name):
            if name in ("name", "input"):
                raise AttributeError(
                    f"'{type(self).__name__}' object has no attribute '{name}'"
                )
            return super().__getattribute__(name)

    malformed_tool = MalformedTool()

    # Try to execute the malformed tool
    result = await toolbox.invoke_agent_tool(malformed_tool)

    # Check that the result indicates an error about missing attributes
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "tu_456"
    assert (
        "missing" in result["content"].lower() or "invalid" in result["content"].lower()
    )


async def test_invoke_tool_with_empty_toolspec():
    """Test invoking a tool with an empty or invalid tool specification"""
    context = MagicMock()

    # Test with None
    result = await invoke_tool(context, None)
    assert "Invalid tool specification" in result["content"]

    # Test with dict instead of proper tool_use object
    result = await invoke_tool(context, {"type": "tool_use"})
    assert "Invalid tool specification" in result["content"]

    # Create a mock that will raise AttributeError when name or input is accessed
    class RestrictedMock:
        type = "tool_use"
        id = "mock_id"

        def __getattribute__(self, name):
            if name in ("name", "input"):
                raise AttributeError(
                    f"'{type(self).__name__}' object has no attribute '{name}'"
                )
            return super().__getattribute__(name)

    # Test with our custom mock missing required attributes
    mock_tool = RestrictedMock()
    result = await invoke_tool(context, mock_tool)
    assert "Invalid tool specification" in result["content"]
