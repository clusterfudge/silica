"""Tests for user tool schema validation.

Tests the validate_tool_schema() function and related functionality
that prevents invalid tool specs from causing API failures.
"""

from pathlib import Path
from unittest.mock import MagicMock

from silica.developer.tools.user_tools import (
    validate_tool_schema,
    DiscoveredTool,
    ToolMetadata,
    VALID_PARAM_TYPES,
)


class TestValidateToolSchema:
    """Tests for validate_tool_schema() function."""

    def test_valid_minimal_spec(self):
        """Test that a minimal valid spec passes validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is True
        assert errors == []

    def test_valid_full_spec(self):
        """Test that a full valid spec with parameters passes validation."""
        spec = {
            "name": "my_tool",
            "description": "A tool that does something",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "A name"},
                    "count": {"type": "integer", "description": "A count"},
                    "enabled": {"type": "boolean", "description": "Whether enabled"},
                    "ratio": {"type": "number", "description": "A ratio"},
                    "items": {"type": "array", "description": "A list of items"},
                    "config": {"type": "object", "description": "Configuration"},
                },
                "required": ["name", "count"],
            },
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is True
        assert errors == []

    def test_not_a_dict(self):
        """Test that non-dict spec fails validation."""
        is_valid, errors = validate_tool_schema("not a dict")
        assert is_valid is False
        assert "Tool spec must be a dictionary" in errors

        is_valid, errors = validate_tool_schema([1, 2, 3])
        assert is_valid is False
        assert "Tool spec must be a dictionary" in errors

    def test_missing_name(self):
        """Test that missing name field fails validation."""
        spec = {
            "description": "A test tool",
            "input_schema": {"type": "object", "properties": {}},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert "Missing required field: name" in errors

    def test_invalid_name_type(self):
        """Test that non-string name fails validation."""
        spec = {
            "name": 123,
            "description": "A test tool",
            "input_schema": {"type": "object", "properties": {}},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert "Field 'name' must be a string" in errors

    def test_invalid_name_pattern_starts_with_number(self):
        """Test that name starting with number fails validation."""
        spec = {
            "name": "123tool",
            "description": "A test tool",
            "input_schema": {"type": "object", "properties": {}},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert any("Invalid tool name" in e and "123tool" in e for e in errors)

    def test_invalid_name_pattern_special_chars(self):
        """Test that name with special characters fails validation."""
        spec = {
            "name": "my-tool",  # Hyphens not allowed
            "description": "A test tool",
            "input_schema": {"type": "object", "properties": {}},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert any("Invalid tool name" in e for e in errors)

    def test_valid_name_with_underscore(self):
        """Test that name with underscores is valid."""
        spec = {
            "name": "my_tool_v2",
            "description": "A test tool",
            "input_schema": {"type": "object", "properties": {}},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is True

    def test_valid_name_starting_with_underscore(self):
        """Test that name starting with underscore is valid."""
        spec = {
            "name": "_private_tool",
            "description": "A test tool",
            "input_schema": {"type": "object", "properties": {}},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is True

    def test_missing_description(self):
        """Test that missing description field fails validation."""
        spec = {
            "name": "test_tool",
            "input_schema": {"type": "object", "properties": {}},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert "Missing required field: description" in errors

    def test_invalid_description_type(self):
        """Test that non-string description fails validation."""
        spec = {
            "name": "test_tool",
            "description": 123,
            "input_schema": {"type": "object", "properties": {}},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert "Field 'description' must be a string" in errors

    def test_missing_input_schema(self):
        """Test that missing input_schema field fails validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert "Missing required field: input_schema" in errors

    def test_invalid_input_schema_type(self):
        """Test that non-dict input_schema fails validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": "not a dict",
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert "Field 'input_schema' must be an object" in errors

    def test_missing_input_schema_type_field(self):
        """Test that missing input_schema.type fails validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {"properties": {}},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert "input_schema missing required field: type" in errors

    def test_invalid_input_schema_type_value(self):
        """Test that input_schema.type != 'object' fails validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {"type": "array", "properties": {}},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert any("input_schema.type must be 'object'" in e for e in errors)

    def test_missing_properties(self):
        """Test that missing input_schema.properties fails validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {"type": "object"},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert "input_schema missing required field: properties" in errors

    def test_invalid_properties_type(self):
        """Test that non-dict properties fails validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {"type": "object", "properties": []},
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert "input_schema.properties must be an object" in errors

    def test_property_missing_type(self):
        """Test that property without type fails validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"description": "A name"}},
            },
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert any("Property 'name' missing required field: type" in e for e in errors)

    def test_property_invalid_type_value(self):
        """Test that property with invalid type fails validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "invalid_type"}},
            },
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert any("invalid type 'invalid_type'" in e for e in errors)

    def test_all_valid_property_types(self):
        """Test that all valid property types are accepted."""
        for prop_type in VALID_PARAM_TYPES:
            spec = {
                "name": "test_tool",
                "description": "A test tool",
                "input_schema": {
                    "type": "object",
                    "properties": {"param": {"type": prop_type}},
                },
            }
            is_valid, errors = validate_tool_schema(spec)
            assert is_valid is True, f"Type '{prop_type}' should be valid: {errors}"

    def test_required_not_array(self):
        """Test that non-array required field fails validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": "name",  # Should be array
            },
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert "input_schema.required must be an array" in errors

    def test_required_non_string_item(self):
        """Test that non-string item in required fails validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": [123],
            },
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert any("required[0] must be a string" in e for e in errors)

    def test_required_references_nonexistent_property(self):
        """Test that required referencing non-existent property fails validation."""
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["nonexistent"],
            },
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert any("non-existent property: 'nonexistent'" in e for e in errors)

    def test_multiple_errors(self):
        """Test that multiple errors are all reported."""
        spec = {
            "name": "123invalid",
            # Missing description
            "input_schema": {
                "type": "array",  # Wrong type
                "properties": {"p": {"type": "invalid"}},
                "required": ["missing"],
            },
        }
        is_valid, errors = validate_tool_schema(spec)
        assert is_valid is False
        assert len(errors) >= 3  # Should have at least 3 errors


class TestDiscoveredToolSchemaFields:
    """Tests for schema_valid and schema_errors fields on DiscoveredTool."""

    def test_default_values(self):
        """Test that default values are correct."""
        tool = DiscoveredTool(
            name="test",
            path=Path("/tmp/test.py"),
            spec={},
            metadata=ToolMetadata(),
        )
        assert tool.schema_valid is True
        assert tool.schema_errors == []

    def test_explicit_valid(self):
        """Test explicit valid schema."""
        tool = DiscoveredTool(
            name="test",
            path=Path("/tmp/test.py"),
            spec={},
            metadata=ToolMetadata(),
            schema_valid=True,
            schema_errors=[],
        )
        assert tool.schema_valid is True
        assert tool.schema_errors == []

    def test_explicit_invalid(self):
        """Test explicit invalid schema with errors."""
        errors = ["Missing description", "Invalid type"]
        tool = DiscoveredTool(
            name="test",
            path=Path("/tmp/test.py"),
            spec={},
            metadata=ToolMetadata(),
            schema_valid=False,
            schema_errors=errors,
        )
        assert tool.schema_valid is False
        assert tool.schema_errors == errors


class TestToolboxSchemasFiltering:
    """Tests for Toolbox.schemas() filtering of invalid tools."""

    def test_valid_tools_included(self):
        """Test that valid user tools are included in schemas."""
        from silica.developer.toolbox import Toolbox

        context = MagicMock()
        context.user_interface = MagicMock()

        toolbox = Toolbox(context, tool_names=[])
        toolbox.user_tools.clear()

        valid_spec = {
            "name": "valid_tool",
            "description": "A valid tool",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }
        toolbox.user_tools["valid_tool"] = DiscoveredTool(
            name="valid_tool",
            path=Path("/tmp/valid.py"),
            spec=valid_spec,
            metadata=ToolMetadata(),
            schema_valid=True,
            schema_errors=[],
        )

        schemas = toolbox.schemas(enable_caching=False)
        tool_names = [s["name"] for s in schemas]
        assert "valid_tool" in tool_names

    def test_invalid_tools_excluded(self):
        """Test that invalid user tools are excluded from schemas."""
        from silica.developer.toolbox import Toolbox

        context = MagicMock()
        context.user_interface = MagicMock()

        toolbox = Toolbox(context, tool_names=[])
        toolbox.user_tools.clear()

        invalid_spec = {"name": "invalid_tool"}  # Missing required fields
        toolbox.user_tools["invalid_tool"] = DiscoveredTool(
            name="invalid_tool",
            path=Path("/tmp/invalid.py"),
            spec=invalid_spec,
            metadata=ToolMetadata(),
            schema_valid=False,
            schema_errors=["Missing description", "Missing input_schema"],
        )

        schemas = toolbox.schemas(enable_caching=False)
        tool_names = [s["name"] for s in schemas]
        assert "invalid_tool" not in tool_names

    def test_mixed_valid_and_invalid(self):
        """Test that only valid tools are included when mixed."""
        from silica.developer.toolbox import Toolbox

        context = MagicMock()
        context.user_interface = MagicMock()

        toolbox = Toolbox(context, tool_names=[])
        toolbox.user_tools.clear()

        # Add valid tool
        valid_spec = {
            "name": "valid_tool",
            "description": "A valid tool",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }
        toolbox.user_tools["valid_tool"] = DiscoveredTool(
            name="valid_tool",
            path=Path("/tmp/valid.py"),
            spec=valid_spec,
            metadata=ToolMetadata(),
            schema_valid=True,
            schema_errors=[],
        )

        # Add invalid tool
        invalid_spec = {"name": "invalid_tool"}
        toolbox.user_tools["invalid_tool"] = DiscoveredTool(
            name="invalid_tool",
            path=Path("/tmp/invalid.py"),
            spec=invalid_spec,
            metadata=ToolMetadata(),
            schema_valid=False,
            schema_errors=["Missing fields"],
        )

        schemas = toolbox.schemas(enable_caching=False)
        tool_names = [s["name"] for s in schemas]

        assert "valid_tool" in tool_names
        assert "invalid_tool" not in tool_names

    def test_invalid_tool_doesnt_override_builtin(self):
        """Test that invalid user tool doesn't hide a builtin with same name."""
        from silica.developer.toolbox import Toolbox

        context = MagicMock()
        context.user_interface = MagicMock()

        # Use just the read_file tool as a builtin
        toolbox = Toolbox(context, tool_names=["read_file"])
        toolbox.user_tools.clear()

        # Add invalid user tool with same name as builtin
        invalid_spec = {"name": "read_file"}  # Missing required fields
        toolbox.user_tools["read_file"] = DiscoveredTool(
            name="read_file",
            path=Path("/tmp/read_file.py"),
            spec=invalid_spec,
            metadata=ToolMetadata(),
            schema_valid=False,
            schema_errors=["Missing fields"],
        )

        schemas = toolbox.schemas(enable_caching=False)
        tool_names = [s["name"] for s in schemas]

        # The builtin should still be present since user tool is invalid
        assert "read_file" in tool_names
        # And it should have the builtin's description
        read_file_schema = next(s for s in schemas if s["name"] == "read_file")
        assert "sandbox" in read_file_schema["description"].lower()


class TestToolsCommandSchemaStatus:
    """Tests for /tools command showing schema validation status."""

    def test_tool_info_includes_schema_fields(self):
        """Test that tool_info dict includes schema validation fields."""
        from silica.developer.tools.user_tools import discover_tools

        # This tests the actual discover_tools output
        tools = discover_tools(check_auth=False)

        for tool in tools:
            # Every discovered tool should have schema_valid set
            assert hasattr(tool, "schema_valid")
            assert isinstance(tool.schema_valid, bool)
            assert hasattr(tool, "schema_errors")
            assert isinstance(tool.schema_errors, list)

    def test_valid_tools_have_empty_errors(self):
        """Test that valid tools have empty schema_errors list."""
        from silica.developer.tools.user_tools import discover_tools

        tools = discover_tools(check_auth=False)

        for tool in tools:
            if tool.schema_valid:
                assert (
                    tool.schema_errors == []
                ), f"Valid tool {tool.name} has errors: {tool.schema_errors}"
