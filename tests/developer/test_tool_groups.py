"""Tests for tool groups functionality in the @tool decorator."""

import unittest
from silica.developer.tools.framework import tool, get_tool_group
from silica.developer.context import AgentContext


class TestToolGroups(unittest.TestCase):
    """Test suite for tool groups functionality."""

    def test_bare_decorator(self):
        """Test @tool without parentheses."""

        @tool
        def my_tool(context: "AgentContext"):
            """A simple tool."""
            return "result"

        # Should work and have no group
        self.assertIsNone(get_tool_group(my_tool))
        self.assertIsNone(my_tool._group)
        # Should still have schema
        self.assertEqual(my_tool.schema()["name"], "my_tool")

    def test_empty_parentheses(self):
        """Test @tool() with empty parentheses."""

        @tool()
        def my_tool(context: "AgentContext"):
            """A simple tool."""
            return "result"

        # Should work and have no group
        self.assertIsNone(get_tool_group(my_tool))
        self.assertIsNone(my_tool._group)
        # Should still have schema
        self.assertEqual(my_tool.schema()["name"], "my_tool")

    def test_group_only(self):
        """Test @tool(group="MyGroup")."""

        @tool(group="MyGroup")
        def my_tool(context: "AgentContext"):
            """A simple tool."""
            return "result"

        # Should have the specified group
        self.assertEqual(get_tool_group(my_tool), "MyGroup")
        self.assertEqual(my_tool._group, "MyGroup")
        # Should still have schema
        self.assertEqual(my_tool.schema()["name"], "my_tool")

    def test_max_concurrency_only(self):
        """Test @tool(max_concurrency=2)."""

        @tool(max_concurrency=2)
        def my_tool(context: "AgentContext"):
            """A simple tool."""
            return "result"

        # Should have no group
        self.assertIsNone(get_tool_group(my_tool))
        self.assertIsNone(my_tool._group)
        # Should have max_concurrency set
        self.assertEqual(my_tool._max_concurrency, 2)
        # Should still have schema
        self.assertEqual(my_tool.schema()["name"], "my_tool")

    def test_group_and_max_concurrency(self):
        """Test @tool(group="MyGroup", max_concurrency=2)."""

        @tool(group="MyGroup", max_concurrency=2)
        def my_tool(context: "AgentContext"):
            """A simple tool."""
            return "result"

        # Should have both group and max_concurrency
        self.assertEqual(get_tool_group(my_tool), "MyGroup")
        self.assertEqual(my_tool._group, "MyGroup")
        self.assertEqual(my_tool._max_concurrency, 2)
        # Should still have schema
        self.assertEqual(my_tool.schema()["name"], "my_tool")

    def test_group_not_in_schema(self):
        """Test that group is not included in the schema output."""

        @tool(group="SecretGroup")
        def my_tool(context: "AgentContext", arg1: str):
            """A tool with args.

            Args:
                arg1: First argument
            """
            return arg1

        schema = my_tool.schema()

        # Group should NOT be in schema (it's for internal use only)
        self.assertNotIn("group", schema)
        self.assertNotIn("_group", schema)
        self.assertNotIn("SecretGroup", str(schema))

        # Schema should have expected structure
        self.assertEqual(schema["name"], "my_tool")
        self.assertEqual(schema["description"], "A tool with args.")
        self.assertIn("arg1", schema["input_schema"]["properties"])

    def test_get_tool_group_on_non_tool(self):
        """Test get_tool_group on a function without @tool decorator."""

        def plain_function():
            pass

        # Should return None for non-decorated functions
        self.assertIsNone(get_tool_group(plain_function))

    def test_different_groups(self):
        """Test multiple tools with different groups."""

        @tool(group="FileSystem")
        def read_file(context: "AgentContext"):
            """Read a file."""

        @tool(group="FileSystem")
        def write_file(context: "AgentContext"):
            """Write a file."""

        @tool(group="Network")
        def http_request(context: "AgentContext"):
            """Make HTTP request."""

        @tool
        def no_group_tool(context: "AgentContext"):
            """Tool without group."""

        self.assertEqual(get_tool_group(read_file), "FileSystem")
        self.assertEqual(get_tool_group(write_file), "FileSystem")
        self.assertEqual(get_tool_group(http_request), "Network")
        self.assertIsNone(get_tool_group(no_group_tool))

    def test_function_execution_with_group(self):
        """Test that decorated functions still execute correctly."""

        class MockContext:
            pass

        @tool(group="TestGroup")
        def add_numbers(context: "AgentContext", a: int, b: int) -> int:
            """Add two numbers.

            Args:
                a: First number
                b: Second number
            """
            return a + b

        ctx = MockContext()
        result = add_numbers(ctx, 1, 2)
        self.assertEqual(result, 3)

    def test_async_function_with_group(self):
        """Test that async functions work with group parameter."""
        import asyncio

        @tool(group="AsyncGroup")
        async def async_tool(context: "AgentContext"):
            """An async tool."""
            return "async result"

        self.assertEqual(get_tool_group(async_tool), "AsyncGroup")
        # Verify it's still async
        self.assertTrue(asyncio.iscoroutinefunction(async_tool))


if __name__ == "__main__":
    unittest.main()
