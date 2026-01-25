"""MCP (Model Context Protocol) integration for Silica.

This module provides MCP host capabilities, allowing Silica to connect to
MCP-compliant servers and expose their tools to the AI agent.

Key components:
- MCPClient: Wrapper around the MCP SDK's ClientSession
- MCPToolManager: Manages multiple MCP server connections
- MCPConfig: Configuration loading and validation
- Schema utilities: Convert between MCP and Anthropic tool schemas
"""

from silica.developer.mcp.config import MCPConfig, MCPServerConfig
from silica.developer.mcp.client import MCPClient
from silica.developer.mcp.manager import MCPToolManager
from silica.developer.mcp.schema import mcp_to_anthropic_schema, anthropic_to_mcp_schema

__all__ = [
    "MCPConfig",
    "MCPServerConfig",
    "MCPClient",
    "MCPToolManager",
    "mcp_to_anthropic_schema",
    "anthropic_to_mcp_schema",
]
