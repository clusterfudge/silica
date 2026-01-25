"""Agent tools for MCP server management.

These tools allow the AI agent to dynamically manage MCP servers during a session,
complementing the /mcp CLI commands which are for interactive user use.
"""

from silica.developer.context import AgentContext
from silica.developer.tools.framework import tool


@tool(group="MCP")
async def mcp_list_servers(context: AgentContext) -> str:
    """List all configured MCP servers and their status.

    Returns information about each server including:
    - Connection status (connected/disconnected)
    - Number of tools available
    - Cache setting (on/off)
    - Authentication status if applicable
    """
    toolbox = context.toolbox
    if not toolbox or not toolbox.mcp_manager:
        return "MCP is not configured. No MCP servers found."

    manager = toolbox.mcp_manager
    statuses = manager.get_server_status()

    if not statuses:
        return "No MCP servers configured."

    lines = ["MCP Servers:"]
    for status in statuses:
        conn_status = "connected" if status.connected else "disconnected"
        tool_count = f"{status.tool_count} tools" if status.connected else "-"
        cache_status = "cache: on" if status.cache_enabled else "cache: off"

        auth_text = ""
        if status.auth_status:
            auth_map = {
                "authenticated": "auth: ✓",
                "expired": "auth: ✗ expired",
                "required": "auth: ⚠ required",
            }
            auth_text = f"  {auth_map.get(status.auth_status, '')}"

        lines.append(
            f"  {status.name}: {conn_status}, {tool_count}, {cache_status}{auth_text}"
        )

    return "\n".join(lines)


@tool(group="MCP")
async def mcp_connect(context: AgentContext, server: str) -> str:
    """Connect to an MCP server (or reconnect if already connected).

    Args:
        server: Name of the server to connect to
    """
    toolbox = context.toolbox
    if not toolbox or not toolbox.mcp_manager:
        return "MCP is not configured."

    manager = toolbox.mcp_manager

    try:
        await manager.connect_server(server)
        client = manager._clients.get(server)
        tool_count = len(client.tools) if client else 0
        return f"Connected to '{server}' with {tool_count} tools"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Failed to connect to '{server}': {e}"


@tool(group="MCP")
async def mcp_disconnect(context: AgentContext, server: str) -> str:
    """Disconnect from an MCP server.

    Args:
        server: Name of the server to disconnect from
    """
    toolbox = context.toolbox
    if not toolbox or not toolbox.mcp_manager:
        return "MCP is not configured."

    manager = toolbox.mcp_manager

    if server not in manager._clients:
        return f"Server '{server}' is not connected"

    await manager.disconnect_server(server)
    return f"Disconnected from '{server}'"


@tool(group="MCP")
async def mcp_set_cache(context: AgentContext, server: str, enabled: bool) -> str:
    """Toggle caching for an MCP server's tool schemas.

    When caching is disabled, tool schemas are refreshed before each API call.
    This is useful for development/iteration on MCP servers.

    Args:
        server: Name of the server to configure
        enabled: Whether to enable caching (true) or disable it (false)
    """
    toolbox = context.toolbox
    if not toolbox or not toolbox.mcp_manager:
        return "MCP is not configured."

    manager = toolbox.mcp_manager

    try:
        manager.set_cache_enabled(server, enabled)
        status = "enabled" if enabled else "disabled"
        return f"Caching {status} for server '{server}'"
    except ValueError as e:
        return f"Error: {e}"


@tool(group="MCP")
async def mcp_refresh(context: AgentContext, server: str | None = None) -> str:
    """Force refresh tool schemas from MCP server(s).

    If server is not specified, refreshes all connected servers.

    Args:
        server: Optional server name to refresh (None for all)
    """
    toolbox = context.toolbox
    if not toolbox or not toolbox.mcp_manager:
        return "MCP is not configured."

    manager = toolbox.mcp_manager

    try:
        await manager.refresh_schemas(server)
        if server:
            client = manager._clients.get(server)
            tool_count = len(client.tools) if client else 0
            return f"Refreshed {tool_count} tools from '{server}'"
        else:
            total_tools = sum(len(c.tools) for c in manager._clients.values())
            return f"Refreshed {total_tools} tools from all servers"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Failed to refresh schemas: {e}"


@tool(group="MCP")
async def mcp_list_tools(context: AgentContext, server: str | None = None) -> str:
    """List tools available from MCP server(s).

    Args:
        server: Optional server name to filter by (None for all servers)
    """
    toolbox = context.toolbox
    if not toolbox or not toolbox.mcp_manager:
        return "MCP is not configured."

    manager = toolbox.mcp_manager
    tools = manager.get_all_tools()

    if server:
        tools = [t for t in tools if t.server_name == server]

    if not tools:
        if server:
            return f"No tools from server '{server}'"
        else:
            return "No MCP tools available"

    # Group tools by server
    by_server: dict[str, list] = {}
    for t in tools:
        by_server.setdefault(t.server_name, []).append(t)

    lines = []
    for srv_name, srv_tools in sorted(by_server.items()):
        lines.append(f"\n{srv_name} ({len(srv_tools)} tools):")
        for t in sorted(srv_tools, key=lambda x: x.name):
            desc = (
                t.description[:60] + "..." if len(t.description) > 60 else t.description
            )
            lines.append(f"  {t.name}: {desc}")

    return "\n".join(lines)


@tool(group="MCP")
async def mcp_auth(context: AgentContext, server: str) -> str:
    """Initiate authentication for an MCP server.

    Starts the authentication flow for the specified server. This will:
    - For OAuth servers: Open browser for authorization or prompt for auth code
    - For API key servers: Prompt for the API key

    Use this when a server requires authentication before it can be used.

    Args:
        server: Name of the server to authenticate
    """
    toolbox = context.toolbox
    if not toolbox or not toolbox.mcp_manager:
        return "MCP is not configured."

    manager = toolbox.mcp_manager

    # Check if server exists
    if not manager._config:
        return "No MCP configuration loaded"

    server_config = manager._config.servers.get(server)
    if not server_config:
        return f"Server '{server}' not found in configuration"

    # Check if server has auth configuration
    if not server_config.auth:
        return f"Server '{server}' does not require authentication"

    # Create auth handler with prompt callback
    from silica.developer.mcp.auth import MCPAuthHandler
    from silica.developer.mcp.credentials import MCPCredentialStore

    store = MCPCredentialStore()

    # For agent tool context, use simple input() for prompts
    # The agent tool runs in an async context but auth flows need sync input
    def sync_prompt(msg: str) -> str:
        return input(msg)

    handler = MCPAuthHandler(
        credential_store=store,
        open_browser=True,  # Try to open browser automatically
        prompt_callback=sync_prompt,
    )

    # Check current auth status
    status = handler.get_auth_status(server_config)
    if status == "authenticated":
        return f"Server '{server}' is already authenticated. Use mcp_auth_revoke to revoke credentials first."

    # Run the authentication flow
    try:
        await handler.authenticate(server_config)
        auth_type = server_config.auth.type

        if auth_type == "oauth":
            return f"Successfully authenticated '{server}' via OAuth"
        else:
            return f"Successfully authenticated '{server}' with API key"

    except Exception as e:
        from silica.developer.mcp.auth import AuthFlowCancelled

        if isinstance(e, AuthFlowCancelled):
            return f"Authentication cancelled for '{server}'"
        return f"Authentication failed for '{server}': {e}"


@tool(group="MCP")
async def mcp_auth_revoke(context: AgentContext, server: str) -> str:
    """Revoke stored credentials for an MCP server.

    Removes any stored authentication credentials (OAuth tokens or API keys)
    for the specified server. After revoking, the server will require
    re-authentication.

    Args:
        server: Name of the server to revoke credentials for
    """
    toolbox = context.toolbox
    if not toolbox or not toolbox.mcp_manager:
        return "MCP is not configured."

    manager = toolbox.mcp_manager

    # Check if server exists
    if not manager._config:
        return "No MCP configuration loaded"

    server_config = manager._config.servers.get(server)
    if not server_config:
        return f"Server '{server}' not found in configuration"

    # Check if server has auth configuration
    if not server_config.auth:
        return f"Server '{server}' does not have authentication configured"

    # Create credential store and revoke
    from silica.developer.mcp.credentials import MCPCredentialStore

    store = MCPCredentialStore()

    if not store.has_credentials(server):
        return f"No credentials stored for server '{server}'"

    store.delete_credentials(server)
    return f"Credentials revoked for server '{server}'. Re-authentication will be required."


@tool(group="MCP")
async def mcp_auth_status(context: AgentContext, server: str | None = None) -> str:
    """Check authentication status for MCP server(s).

    Shows detailed authentication status including:
    - Authentication type (OAuth, API key, etc.)
    - Whether credentials are stored
    - Whether credentials are expired (for OAuth)

    Args:
        server: Optional server name to check (None for all servers with auth)
    """
    toolbox = context.toolbox
    if not toolbox or not toolbox.mcp_manager:
        return "MCP is not configured."

    manager = toolbox.mcp_manager

    if not manager._config:
        return "No MCP configuration loaded"

    # Collect servers to check
    if server:
        server_config = manager._config.servers.get(server)
        if not server_config:
            return f"Server '{server}' not found"
        servers_to_check = [(server, server_config)]
    else:
        # All servers with auth config
        servers_to_check = [
            (name, config)
            for name, config in manager._config.servers.items()
            if config.auth
        ]

    if not servers_to_check:
        return "No MCP servers with authentication configuration"

    from silica.developer.mcp.auth import MCPAuthHandler
    from silica.developer.mcp.credentials import MCPCredentialStore

    store = MCPCredentialStore()
    handler = MCPAuthHandler(credential_store=store)

    lines = ["MCP Authentication Status:"]
    for name, config in servers_to_check:
        auth_type = config.auth.type if config.auth else "none"
        status = handler.get_auth_status(config)

        # Format status nicely
        status_map = {
            "authenticated": "✓ authenticated",
            "expired": "⚠ expired",
            "not_configured": "✗ not configured",
            "not_required": "- not required",
        }
        status_text = status_map.get(status, status)

        lines.append(f"  {name}: {auth_type} - {status_text}")

        # Add expiry info for OAuth
        if status == "authenticated" and auth_type == "oauth":
            creds = store.get_credentials(name)
            if creds and hasattr(creds, "expires_at") and creds.expires_at:
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                if creds.expires_at > now:
                    remaining = creds.expires_at - now
                    hours = remaining.total_seconds() / 3600
                    if hours < 1:
                        lines.append(f"           expires in {int(hours * 60)} minutes")
                    else:
                        lines.append(f"           expires in {hours:.1f} hours")

    return "\n".join(lines)
