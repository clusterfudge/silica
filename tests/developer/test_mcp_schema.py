"""Tests for MCP schema conversion utilities."""

from silica.developer.mcp.schema import (
    anthropic_to_mcp_schema,
    mcp_to_anthropic_schema,
    prefix_tool_name,
    unprefix_tool_name,
    validate_tool_schema,
)


class TestPrefixToolName:
    """Tests for tool name prefixing."""

    def test_simple_prefix(self):
        """Test basic prefixing."""
        result = prefix_tool_name("query", "sqlite")
        assert result == "mcp_sqlite_query"

    def test_prefix_with_special_chars(self):
        """Test prefixing with special characters in server name."""
        result = prefix_tool_name("read", "my-server")
        assert result == "mcp_my_server_read"

    def test_prefix_with_dots(self):
        """Test prefixing with dots in server name."""
        result = prefix_tool_name("execute", "server.local")
        assert result == "mcp_server_local_execute"


class TestUnprefixToolName:
    """Tests for extracting server and tool from prefixed name."""

    def test_simple_unprefix(self):
        """Test basic unprefixing."""
        result = unprefix_tool_name("mcp_sqlite_query")
        assert result == ("sqlite", "query")

    def test_tool_with_underscores(self):
        """Test unprefixing when tool name has underscores."""
        result = unprefix_tool_name("mcp_server_read_file")
        assert result == ("server", "read_file")

    def test_not_prefixed(self):
        """Test with non-prefixed name."""
        result = unprefix_tool_name("regular_tool")
        assert result is None

    def test_invalid_prefix(self):
        """Test with invalid prefix format."""
        result = unprefix_tool_name("mcp_")
        assert result is None


class TestMcpToAnthropicSchema:
    """Tests for MCP to Anthropic schema conversion."""

    def test_basic_conversion(self):
        """Test basic schema conversion."""
        mcp_tool = {
            "name": "query",
            "description": "Run a SQL query",
            "inputSchema": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        }
        result = mcp_to_anthropic_schema(mcp_tool, "sqlite")

        assert result["name"] == "mcp_sqlite_query"
        assert result["description"] == "Run a SQL query"
        assert "input_schema" in result
        assert result["input_schema"]["type"] == "object"
        assert "sql" in result["input_schema"]["properties"]

    def test_missing_description(self):
        """Test conversion with missing description."""
        mcp_tool = {
            "name": "tool",
            "inputSchema": {"type": "object"},
        }
        result = mcp_to_anthropic_schema(mcp_tool, "server")
        assert result["description"] == ""

    def test_missing_input_schema(self):
        """Test conversion with missing input schema."""
        mcp_tool = {"name": "tool", "description": "desc"}
        result = mcp_to_anthropic_schema(mcp_tool, "server")
        assert result["input_schema"] == {}

    def test_already_snake_case(self):
        """Test when MCP tool uses snake_case (non-standard)."""
        mcp_tool = {
            "name": "tool",
            "input_schema": {"type": "object"},
        }
        result = mcp_to_anthropic_schema(mcp_tool, "server")
        assert result["input_schema"] == {"type": "object"}


class TestAnthropicToMcpSchema:
    """Tests for Anthropic to MCP schema conversion."""

    def test_basic_conversion(self):
        """Test basic schema conversion."""
        anthropic_tool = {
            "name": "mcp_sqlite_query",
            "description": "Run a SQL query",
            "input_schema": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
            },
        }
        result = anthropic_to_mcp_schema(anthropic_tool)

        assert result["name"] == "mcp_sqlite_query"
        assert result["description"] == "Run a SQL query"
        assert "inputSchema" in result
        assert result["inputSchema"]["type"] == "object"

    def test_missing_fields(self):
        """Test conversion with missing optional fields."""
        anthropic_tool = {"name": "tool"}
        result = anthropic_to_mcp_schema(anthropic_tool)
        assert result["name"] == "tool"
        assert result["description"] == ""
        assert result["inputSchema"] == {}


class TestValidateToolSchema:
    """Tests for tool schema validation."""

    def test_valid_schema(self):
        """Test validation of valid schema."""
        schema = {
            "name": "my_tool",
            "description": "A tool",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        }
        errors = validate_tool_schema(schema)
        assert errors == []

    def test_missing_name(self):
        """Test validation with missing name."""
        schema = {"description": "A tool"}
        errors = validate_tool_schema(schema)
        assert any("name" in e for e in errors)

    def test_empty_name(self):
        """Test validation with empty name."""
        schema = {"name": "", "description": "A tool"}
        errors = validate_tool_schema(schema)
        assert any("name" in e for e in errors)

    def test_invalid_input_schema_type(self):
        """Test validation with non-object input_schema."""
        schema = {
            "name": "tool",
            "input_schema": "not an object",
        }
        errors = validate_tool_schema(schema)
        assert any("object" in e for e in errors)

    def test_input_schema_wrong_type(self):
        """Test validation when input_schema.type is not 'object'."""
        schema = {
            "name": "tool",
            "input_schema": {"type": "string"},
        }
        errors = validate_tool_schema(schema)
        assert any("object" in e for e in errors)

    def test_valid_with_mcp_key(self):
        """Test validation accepts inputSchema key too."""
        schema = {
            "name": "tool",
            "inputSchema": {"type": "object"},
        }
        errors = validate_tool_schema(schema)
        assert errors == []
