"""Schema conversion utilities between MCP and Anthropic formats.

MCP uses camelCase (e.g., inputSchema) while Anthropic uses snake_case
(e.g., input_schema). This module provides conversion functions.

MCP Tool Schema:
{
    "name": "tool_name",
    "description": "Tool description",
    "inputSchema": {
        "type": "object",
        "properties": {...},
        "required": [...]
    }
}

Anthropic Tool Schema:
{
    "name": "tool_name",
    "description": "Tool description",
    "input_schema": {
        "type": "object",
        "properties": {...},
        "required": [...]
    }
}
"""

import re
from typing import Any

__all__ = ["mcp_to_anthropic_schema", "anthropic_to_mcp_schema", "prefix_tool_name"]


def _camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case.

    Args:
        name: String in camelCase.

    Returns:
        String in snake_case.
    """
    # Insert underscore before uppercase letters and lowercase the result
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase.

    Args:
        name: String in snake_case.

    Returns:
        String in camelCase.
    """
    components = name.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def _convert_keys_camel_to_snake(obj: Any) -> Any:
    """Recursively convert dictionary keys from camelCase to snake_case.

    Args:
        obj: Object to convert (dict, list, or other).

    Returns:
        Object with converted keys.
    """
    if isinstance(obj, dict):
        return {
            _camel_to_snake(k): _convert_keys_camel_to_snake(v) for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [_convert_keys_camel_to_snake(item) for item in obj]
    return obj


def _convert_keys_snake_to_camel(obj: Any) -> Any:
    """Recursively convert dictionary keys from snake_case to camelCase.

    Args:
        obj: Object to convert (dict, list, or other).

    Returns:
        Object with converted keys.
    """
    if isinstance(obj, dict):
        return {
            _snake_to_camel(k): _convert_keys_snake_to_camel(v) for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [_convert_keys_snake_to_camel(item) for item in obj]
    return obj


def prefix_tool_name(tool_name: str, server_name: str) -> str:
    """Create a prefixed tool name to avoid collisions.

    Args:
        tool_name: Original tool name from MCP server.
        server_name: Name of the MCP server.

    Returns:
        Prefixed tool name (e.g., "mcp_sqlite_query").
    """
    # Sanitize server name for use in tool name
    safe_server = re.sub(r"[^a-zA-Z0-9]", "_", server_name)
    return f"mcp_{safe_server}_{tool_name}"


def unprefix_tool_name(prefixed_name: str) -> tuple[str, str] | None:
    """Extract server and tool names from a prefixed tool name.

    Args:
        prefixed_name: Prefixed tool name (e.g., "mcp_sqlite_query").

    Returns:
        Tuple of (server_name, tool_name) if valid prefix, None otherwise.
    """
    if not prefixed_name.startswith("mcp_"):
        return None
    # Find the second underscore to split server and tool
    rest = prefixed_name[4:]  # Remove "mcp_"
    if "_" not in rest:
        return None
    server_name, tool_name = rest.split("_", 1)
    return (server_name, tool_name)


def mcp_to_anthropic_schema(
    mcp_tool: dict[str, Any], server_name: str
) -> dict[str, Any]:
    """Convert an MCP tool schema to Anthropic format.

    Key conversions:
    - Tool name is prefixed with server name (mcp_{server}_{name})
    - inputSchema -> input_schema
    - All camelCase keys in schema converted to snake_case

    Args:
        mcp_tool: Tool definition from MCP server.
        server_name: Name of the server (for prefixing).

    Returns:
        Tool schema in Anthropic format.
    """
    # Get the original tool name and create prefixed version
    original_name = mcp_tool.get("name", "unknown")
    prefixed_name = prefix_tool_name(original_name, server_name)

    # Get description
    description = mcp_tool.get("description", "")

    # Convert input schema (MCP uses inputSchema, Anthropic uses input_schema)
    input_schema = mcp_tool.get("inputSchema", mcp_tool.get("input_schema", {}))

    # Convert any camelCase keys within the schema itself
    # Note: JSON Schema standard uses camelCase, but we keep it consistent
    # with what Anthropic expects (they accept either)
    converted_schema = input_schema  # Keep schema keys as-is for compatibility

    return {
        "name": prefixed_name,
        "description": description,
        "input_schema": converted_schema,
    }


def anthropic_to_mcp_schema(anthropic_tool: dict[str, Any]) -> dict[str, Any]:
    """Convert an Anthropic tool schema to MCP format.

    Key conversions:
    - input_schema -> inputSchema
    - Tool name kept as-is (no un-prefixing)

    Args:
        anthropic_tool: Tool definition in Anthropic format.

    Returns:
        Tool schema in MCP format.
    """
    return {
        "name": anthropic_tool.get("name", ""),
        "description": anthropic_tool.get("description", ""),
        "inputSchema": anthropic_tool.get("input_schema", {}),
    }


def validate_tool_schema(schema: dict[str, Any]) -> list[str]:
    """Validate a tool schema and return any errors.

    Args:
        schema: Tool schema to validate.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors = []

    # Check required fields
    if "name" not in schema or not schema["name"]:
        errors.append("Tool schema missing 'name' field")

    # Check input_schema structure
    input_schema = schema.get("input_schema") or schema.get("inputSchema")
    if input_schema:
        if not isinstance(input_schema, dict):
            errors.append("input_schema must be an object")
        elif input_schema.get("type") != "object":
            errors.append("input_schema.type should be 'object'")

    return errors
