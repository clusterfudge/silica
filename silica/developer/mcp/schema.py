"""Schema conversion utilities between MCP and Anthropic formats.

MCP uses camelCase (e.g., inputSchema) while Anthropic uses snake_case
(e.g., input_schema). This module provides conversion functions.
"""

from typing import Any

__all__ = ["mcp_to_anthropic_schema", "anthropic_to_mcp_schema"]


def mcp_to_anthropic_schema(
    mcp_tool: dict[str, Any], server_name: str
) -> dict[str, Any]:
    """Convert an MCP tool schema to Anthropic format.

    Args:
        mcp_tool: Tool definition from MCP server.
        server_name: Name of the server (for prefixing).

    Returns:
        Tool schema in Anthropic format.
    """
    # Implementation will be added in task 8d0f0cf9
    raise NotImplementedError("mcp_to_anthropic_schema() not yet implemented")


def anthropic_to_mcp_schema(anthropic_tool: dict[str, Any]) -> dict[str, Any]:
    """Convert an Anthropic tool schema to MCP format.

    Args:
        anthropic_tool: Tool definition in Anthropic format.

    Returns:
        Tool schema in MCP format.
    """
    # Implementation will be added in task 8d0f0cf9
    raise NotImplementedError("anthropic_to_mcp_schema() not yet implemented")
