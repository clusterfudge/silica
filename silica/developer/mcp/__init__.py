"""MCP (Model Context Protocol) integration for Silica.

This module provides MCP host capabilities, allowing Silica to connect to
MCP-compliant servers and expose their tools to the AI agent.

Key components:
- MCPClient: Wrapper around the MCP SDK's ClientSession
- MCPToolManager: Manages multiple MCP server connections
- MCPConfig: Configuration loading and validation
- Schema utilities: Convert between MCP and Anthropic tool schemas
"""

from silica.developer.mcp.client import (
    MCPClient,
    MCPConnectionError,
    MCPServerCrashedError,
    MCPTimeoutError,
    MCPToolError,
    MCPToolInfo,
)
from silica.developer.mcp.config import (
    MCPAuthConfig,
    MCPConfig,
    MCPServerConfig,
    load_mcp_config,
)
from silica.developer.mcp.manager import MCPToolManager, ServerStatus
from silica.developer.mcp.schema import (
    anthropic_to_mcp_schema,
    mcp_to_anthropic_schema,
    prefix_tool_name,
    unprefix_tool_name,
    validate_tool_schema,
)
from silica.developer.mcp.credentials import (
    MCPCredentialStore,
    OAuthCredentials,
    APIKeyCredentials,
    Credentials,
)

__all__ = [
    # Client
    "MCPClient",
    "MCPConnectionError",
    "MCPServerCrashedError",
    "MCPTimeoutError",
    "MCPToolError",
    "MCPToolInfo",
    # Config
    "MCPConfig",
    "MCPServerConfig",
    "MCPAuthConfig",
    "load_mcp_config",
    # Manager
    "MCPToolManager",
    "ServerStatus",
    # Schema
    "mcp_to_anthropic_schema",
    "anthropic_to_mcp_schema",
    "prefix_tool_name",
    "unprefix_tool_name",
    "validate_tool_schema",
    # Credentials
    "MCPCredentialStore",
    "OAuthCredentials",
    "APIKeyCredentials",
    "Credentials",
]
