"""
Tests for Toolbox tools parameter.
"""

from unittest.mock import Mock

import pytest

from silica.developer.context import AgentContext
from silica.developer.toolbox import Toolbox
from silica.developer.tools import ALL_TOOLS, read_file, write_file, list_directory


@pytest.fixture
def mock_context():
    """Create a mock AgentContext."""
    context = Mock(spec=AgentContext)
    context.sandbox = Mock()
    context.user_interface = Mock()
    return context


class TestToolboxToolsParameter:
    """Tests for the tools parameter in Toolbox.__init__."""

    def test_default_uses_all_tools(self, mock_context):
        """Test that default behavior uses ALL_TOOLS."""
        toolbox = Toolbox(mock_context)

        assert toolbox.agent_tools == ALL_TOOLS
        assert len(toolbox.agent_tools) > 0

    def test_tool_names_filters_all_tools(self, mock_context):
        """Test that tool_names parameter filters ALL_TOOLS by name."""
        toolbox = Toolbox(mock_context, tool_names=["read_file", "write_file"])

        assert len(toolbox.agent_tools) == 2
        tool_names = [tool.__name__ for tool in toolbox.agent_tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "list_directory" not in tool_names

    def test_tools_parameter_uses_provided_tools(self, mock_context):
        """Test that tools parameter uses provided tools directly."""
        custom_tools = [read_file, write_file]
        toolbox = Toolbox(mock_context, tools=custom_tools)

        assert toolbox.agent_tools == custom_tools
        assert len(toolbox.agent_tools) == 2
        assert read_file in toolbox.agent_tools
        assert write_file in toolbox.agent_tools

    def test_tools_parameter_takes_precedence(self, mock_context):
        """Test that tools parameter takes precedence over tool_names."""
        custom_tools = [read_file, write_file]
        toolbox = Toolbox(
            mock_context, tool_names=["list_directory"], tools=custom_tools
        )

        # Should use tools, not tool_names
        assert toolbox.agent_tools == custom_tools
        assert len(toolbox.agent_tools) == 2
        assert list_directory not in toolbox.agent_tools

    def test_tools_can_include_custom_functions(self, mock_context):
        """Test that tools parameter can include custom tool functions."""
        from silica.developer.tools.framework import tool

        @tool
        def custom_tool(context: AgentContext, param: str) -> str:
            """A custom tool for testing."""
            return f"Custom: {param}"

        custom_tools = [read_file, custom_tool]
        toolbox = Toolbox(mock_context, tools=custom_tools)

        assert len(toolbox.agent_tools) == 2
        assert read_file in toolbox.agent_tools
        assert custom_tool in toolbox.agent_tools

    def test_empty_tools_list(self, mock_context):
        """Test that an empty tools list creates a toolbox with no agent tools."""
        toolbox = Toolbox(mock_context, tools=[])

        assert toolbox.agent_tools == []
        assert len(toolbox.agent_tools) == 0

    def test_schemas_method_works_with_custom_tools(self, mock_context):
        """Test that schemas() method works with custom tools."""
        custom_tools = [read_file, write_file, list_directory]
        toolbox = Toolbox(mock_context, tools=custom_tools)

        schemas = toolbox.schemas()

        assert len(schemas) == 3
        schema_names = [schema["name"] for schema in schemas]
        assert "read_file" in schema_names
        assert "write_file" in schema_names
        assert "list_directory" in schema_names

    def test_local_cli_tools_always_registered(self, mock_context):
        """Test that local CLI tools are always registered regardless of agent_tools."""
        toolbox = Toolbox(mock_context, tools=[])

        # Even with no agent tools, CLI tools should be registered
        assert len(toolbox.local) > 0
        assert "help" in toolbox.local
        assert "tips" in toolbox.local

    def test_tool_names_with_nonexistent_name(self, mock_context):
        """Test that tool_names with non-existent names are silently filtered out."""
        toolbox = Toolbox(
            mock_context, tool_names=["read_file", "nonexistent_tool", "write_file"]
        )

        # Should only include tools that exist
        assert len(toolbox.agent_tools) == 2
        tool_names = [tool.__name__ for tool in toolbox.agent_tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "nonexistent_tool" not in tool_names


class TestToolboxBackwardCompatibility:
    """Test backward compatibility with existing code."""

    def test_existing_code_with_no_parameters_still_works(self, mock_context):
        """Test that existing code with no parameters still works."""
        # This is how existing code creates toolboxes
        toolbox = Toolbox(mock_context)

        assert toolbox.agent_tools == ALL_TOOLS

    def test_existing_code_with_tool_names_still_works(self, mock_context):
        """Test that existing code with tool_names still works."""
        # This is how subagent code filters tools
        toolbox = Toolbox(mock_context, tool_names=["read_file", "write_file"])

        assert len(toolbox.agent_tools) == 2
        tool_names = [tool.__name__ for tool in toolbox.agent_tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
