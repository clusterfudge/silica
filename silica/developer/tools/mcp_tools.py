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
    - Setup status (if credentials path is configured)
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

        setup_text = ""
        if status.needs_setup:
            setup_text = "  ⚠ needs setup"

        lines.append(
            f"  {status.name}: {conn_status}, {tool_count}, {cache_status}{setup_text}"
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
async def mcp_add_server(
    context: AgentContext,
    name: str,
    command: str,
    args: str | None = None,
    env: str | None = None,
    location: str = "global",
) -> str:
    """Add an MCP server to the configuration.

    The server will be saved to the config file and can be connected on next
    session start or manually with mcp_connect.

    Args:
        name: Server name/identifier (e.g., "sqlite", "github")
        command: Command to run the server (e.g., "npx", "uvx")
        args: JSON array of arguments (e.g., '["-y", "@modelcontextprotocol/server-sqlite"]')
        env: JSON object of environment variables (e.g., '{"GITHUB_TOKEN": "xxx"}')
        location: Where to save - "global" (default), "persona", or "project"
    """
    import json
    from pathlib import Path

    from silica.developer.mcp.config import add_mcp_server

    # Parse args if provided
    parsed_args = []
    if args:
        try:
            parsed_args = json.loads(args)
            if not isinstance(parsed_args, list):
                return "Error: args must be a JSON array"
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in args: {e}"

    # Parse env if provided
    parsed_env = {}
    if env:
        try:
            parsed_env = json.loads(env)
            if not isinstance(parsed_env, dict):
                return "Error: env must be a JSON object"
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in env: {e}"

    # Determine persona/project for location
    persona = None
    project_root = None

    if location == "persona":
        if context.history_base_dir:
            history_path = Path(context.history_base_dir)
            if history_path.parent.name == "personas":
                persona = history_path.name
        if not persona:
            return "Error: Could not determine current persona for persona location"
    elif location == "project":
        project_root = Path.cwd()

    try:
        path = add_mcp_server(
            name=name,
            command=command,
            args=parsed_args,
            env=parsed_env,
            location=location,
            persona=persona,
            project_root=project_root,
        )
        return f"Added server '{name}' to {location} config at {path}\nRestart session or use /mcp connect {name} to connect."
    except Exception as e:
        return f"Error adding server: {e}"


@tool(group="MCP")
async def mcp_remove_server(
    context: AgentContext,
    name: str,
    location: str = "global",
) -> str:
    """Remove an MCP server from the configuration.

    Args:
        name: Server name to remove
        location: Where to remove from - "global" (default), "persona", or "project"
    """
    from pathlib import Path

    from silica.developer.mcp.config import remove_mcp_server

    # Determine persona/project for location
    persona = None
    project_root = None

    if location == "persona":
        if context.history_base_dir:
            history_path = Path(context.history_base_dir)
            if history_path.parent.name == "personas":
                persona = history_path.name
        if not persona:
            return "Error: Could not determine current persona for persona location"
    elif location == "project":
        project_root = Path.cwd()

    try:
        removed = remove_mcp_server(
            name=name,
            location=location,
            persona=persona,
            project_root=project_root,
        )
        if removed:
            return f"Removed server '{name}' from {location} config"
        else:
            return f"Server '{name}' not found in {location} config"
    except Exception as e:
        return f"Error removing server: {e}"
