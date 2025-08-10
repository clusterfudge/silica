"""
Simple test script for unexpected tool specs that doesn't rely on pytest.
"""

import sys
import traceback
import asyncio
from unittest.mock import MagicMock

from silica.developer.tools.framework import invoke_tool
from silica.developer.toolbox import Toolbox
from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode


async def test_invoke_tool_with_empty_toolspec():
    """Test invoking a tool with an empty or invalid tool specification"""
    print("Testing invoke_tool with empty tool spec...")
    context = MagicMock()

    # Test with None
    result = await invoke_tool(context, None)
    assert (
        "Invalid tool specification" in result["content"]
    ), "Should handle None gracefully"
    print("✅ Test with None passed")

    # Test with dict instead of proper tool_use object
    result = await invoke_tool(context, {"type": "tool_use"})
    assert (
        "Invalid tool specification" in result["content"]
    ), "Should handle dict gracefully"
    print("✅ Test with dict passed")

    # Test with MagicMock missing required attributes
    mock_tool = MagicMock()
    mock_tool.type = "tool_use"
    # MagicMock has special behavior - we need to explicitly set name/input to None
    del mock_tool.name
    del mock_tool.input

    print(f"Has name attribute: {hasattr(mock_tool, 'name')}")
    print(f"Has input attribute: {hasattr(mock_tool, 'input')}")
    result = await invoke_tool(context, mock_tool)
    print(f"Result content: {result['content']}")
    assert (
        "Invalid tool specification" in result["content"]
    ), "Should handle missing attributes gracefully"
    print("✅ Test with MagicMock missing attributes passed")


async def test_toolbox_invoke_agent_tool():
    """Test Toolbox.invoke_agent_tool with invalid tool specs"""
    print("Testing Toolbox.invoke_agent_tool with invalid tool specs...")

    # Create a minimal context
    user_interface = MagicMock()
    context = AgentContext.create(
        model_spec={
            "title": "test_model",
            "max_tokens": 1000,
            "pricing": {"input": 0.25, "output": 1.25},
        },
        sandbox_mode=SandboxMode.ALLOW_ALL,
        user_interface=user_interface,
        sandbox_contents=[],  # Empty list for sandbox contents
    )

    # Create a toolbox
    toolbox = Toolbox(context)

    # Test with None
    result = await toolbox.invoke_agent_tool(None)
    assert (
        "Invalid tool specification" in result["content"]
    ), "Should handle None gracefully"
    print("✅ Test with None passed")

    # Test with malformed tool object
    malformed_tool = MagicMock()
    malformed_tool.type = "tool_use"
    malformed_tool.id = "tu_456"
    # Explicitly remove name and input attributes
    del malformed_tool.name
    del malformed_tool.input

    print(
        f"Malformed tool - Has name: {hasattr(malformed_tool, 'name')}, Has input: {hasattr(malformed_tool, 'input')}"
    )
    result = await toolbox.invoke_agent_tool(malformed_tool)
    print(f"Malformed tool result: {result['content']}")
    assert (
        "Invalid tool specification" in result["content"]
    ), "Should handle malformed tool gracefully"
    print("✅ Test with malformed tool passed")

    # Test with unknown tool
    unknown_tool = MagicMock()
    unknown_tool.type = "tool_use"
    unknown_tool.id = "tu_789"
    unknown_tool.name = "nonexistent_tool"  # This tool doesn't exist
    unknown_tool.input = {}

    result = await toolbox.invoke_agent_tool(unknown_tool)
    assert (
        "Unknown function" in result["content"]
    ), "Should handle unknown tool gracefully"
    print("✅ Test with unknown tool passed")


async def main():
    try:
        await test_invoke_tool_with_empty_toolspec()
        await test_toolbox_invoke_agent_tool()
        print("\n🎉 All tests passed!")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
