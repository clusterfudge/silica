from silica.developer.toolbox import Toolbox
from silica.developer.sandbox import SandboxMode
from silica.developer.tools import ALL_TOOLS
from silica.developer.context import AgentContext
from silica.developer.user_interface import UserInterface


class MockUserInterface(UserInterface):
    """Mock user interface for testing."""

    def handle_assistant_message(self, message: str) -> None:
        pass

    def handle_system_message(self, message: str, markdown=True, live=None) -> None:
        pass

    def permission_callback(
        self, action: str, resource: str, sandbox_mode: SandboxMode, action_arguments
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


def test_schemas_are_consistent():
    """Test that schemas() returns consistent results and matches expected format"""
    context = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=MockUserInterface(),
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


def test_agent_schema_matches_schemas():
    """Test that agent_schema matches schemas()"""
    context = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=MockUserInterface(),
    )
    toolbox = Toolbox(context)

    assert (
        toolbox.agent_schema == toolbox.schemas()
    ), "agent_schema should be identical to schemas()"


def test_schemas_match_tools():
    """Test that schemas() generates a schema for each tool"""
    context = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=MockUserInterface(),
    )
    toolbox = Toolbox(context)

    schemas = toolbox.schemas()
    tool_names = {tool.__name__ for tool in ALL_TOOLS}
    schema_names = {schema["name"] for schema in schemas}

    assert tool_names == schema_names, "Schema names should match tool names"
