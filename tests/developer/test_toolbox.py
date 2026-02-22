from silica.developer.toolbox import Toolbox
from silica.developer.sandbox import SandboxMode
from silica.developer.context import AgentContext
from silica.developer.user_interface import UserInterface


class MockUserInterface(UserInterface):
    """Mock user interface for testing."""

    def handle_assistant_message(self, message: str) -> None:
        pass

    def handle_system_message(self, message: str, markdown=True, live=None) -> None:
        pass

    def permission_callback(
        self,
        action: str,
        resource: str,
        sandbox_mode: SandboxMode,
        action_arguments,
        group=None,
    ):
        return True

    def permission_rendering_callback(
        self, action: str, resource: str, action_arguments
    ):
        pass

    def handle_tool_use(self, tool_name: str, tool_params):
        pass

    def handle_tool_result(self, name: str, result, live=None):
        pass

    async def get_user_input(self, prompt: str = "") -> str:
        return ""

    def handle_user_input(self, user_input: str) -> str:
        return user_input

    def display_token_count(self, *args, **kwargs):
        pass

    def display_welcome_message(self):
        pass

    def status(self, message: str, spinner: str = None):
        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return DummyContext()

    def bare(self, message, live=None):
        pass


def test_schemas_are_consistent(persona_base_dir):
    """Test that schemas() returns consistent results and matches expected format"""
    context = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=MockUserInterface(),
        persona_base_directory=persona_base_dir,
    )
    toolbox = Toolbox(context)

    # Get schemas from toolbox
    generated_schemas = toolbox.schemas()

    # Test schema format
    for schema in generated_schemas:
        # Check required top-level fields
        assert "name" in schema
        assert "description" in schema
        assert "input_schema" in schema

        input_schema = schema["input_schema"]
        assert "type" in input_schema
        assert input_schema["type"] == "object"
        assert "properties" in input_schema
        assert "required" in input_schema

        # Check properties format
        for prop_name, prop in input_schema["properties"].items():
            assert "type" in prop
            assert "description" in prop

        # Check required is a list and all required properties exist
        assert isinstance(input_schema["required"], list)
        for req_prop in input_schema["required"]:
            assert req_prop in input_schema["properties"]


def test_agent_schema_matches_schemas(persona_base_dir):
    """Test that agent_schema matches schemas()"""
    context = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=MockUserInterface(),
        persona_base_directory=persona_base_dir,
    )
    toolbox = Toolbox(context)

    assert toolbox.agent_schema == toolbox.schemas(), (
        "agent_schema should be identical to schemas()"
    )


def test_schemas_match_tools(persona_base_dir):
    """Test that schemas() generates a schema for each tool (built-in and user tools)"""
    context = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=MockUserInterface(),
        persona_base_directory=persona_base_dir,
    )
    toolbox = Toolbox(context)

    schemas = toolbox.schemas()
    # Compare with actually loaded tools (not ALL_TOOLS) since some may be filtered
    # Include both built-in tools and user tools
    builtin_tool_names = {tool.__name__ for tool in toolbox.agent_tools}
    user_tool_names = {name for name in toolbox.user_tools.keys()}
    all_tool_names = builtin_tool_names | user_tool_names
    schema_names = {schema["name"] for schema in schemas}

    assert all_tool_names == schema_names, (
        "Schema names should match tool names (built-in + user)"
    )


class TestToolboxMCPIntegration:
    """Tests for MCP tool integration in Toolbox."""

    def test_toolbox_accepts_mcp_manager(self, persona_base_dir):
        """Test that Toolbox can be created with an MCP manager."""
        from unittest.mock import MagicMock

        context = AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=MockUserInterface(),
            persona_base_directory=persona_base_dir,
        )

        mock_manager = MagicMock()
        mock_manager.get_all_tools.return_value = []
        mock_manager.is_mcp_tool.return_value = False

        toolbox = Toolbox(context, mcp_manager=mock_manager)
        assert toolbox.mcp_manager is mock_manager

    def test_toolbox_without_mcp_manager(self, persona_base_dir):
        """Test that Toolbox works without MCP manager."""
        context = AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=MockUserInterface(),
            persona_base_directory=persona_base_dir,
        )

        toolbox = Toolbox(context)
        assert toolbox.mcp_manager is None

    def test_schemas_include_mcp_tools(self, persona_base_dir):
        """Test that MCP tools are included in schemas."""
        from unittest.mock import MagicMock

        from silica.developer.mcp.client import MCPToolInfo

        context = AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=MockUserInterface(),
            persona_base_directory=persona_base_dir,
        )

        mock_tool = MCPToolInfo(
            name="mcp_test_query",
            description="Test MCP tool",
            input_schema={"type": "object", "properties": {}},
            server_name="test",
            original_name="query",
        )

        mock_manager = MagicMock()
        mock_manager.get_all_tools.return_value = [mock_tool]
        mock_manager.is_mcp_tool.return_value = False

        toolbox = Toolbox(context, mcp_manager=mock_manager)
        schemas = toolbox.schemas(enable_caching=False)

        # Check that MCP tool is in schemas
        mcp_tool_names = [s["name"] for s in schemas if s["name"].startswith("mcp_")]
        assert "mcp_test_query" in mcp_tool_names
