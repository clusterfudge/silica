"""
Tool permissions management for per-persona tool access control.

This module provides the ToolPermissions dataclass and PermissionsManager class
for filtering tools based on per-persona configuration stored in tool_permissions.json.

The permissions system supports two modes:
- allowlist: Only explicitly allowed tools/groups are available; deny list acts as exceptions
- denylist: All tools available except explicitly denied ones; allow list is ignored

Special handling:
- If dwr_mode is True, all permissions are bypassed (Danger Will Robinson mode)
- If no tool_permissions.json exists, no tools are available (secure by default)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from .user_tools import DiscoveredTool

# Default permissions file name
PERMISSIONS_FILE = "tool_permissions.json"

# Current schema version
SCHEMA_VERSION = 1


@dataclass
class ToolPermissions:
    """Represents the permissions configuration for a persona.

    Attributes:
        version: Schema version for forward compatibility
        mode: Permission mode - "allowlist" or "denylist"
        allow_tools: Set of tool names that are explicitly allowed
        allow_groups: Set of group names that are explicitly allowed
        deny_tools: Set of tool names that are explicitly denied
        deny_groups: Set of group names that are explicitly denied
        shell_allowed_commands: Set of shell commands that are explicitly allowed
        shell_denied_commands: Set of shell commands that are explicitly denied
        mcp_allowed_servers: Set of MCP server names that are allowed
        mcp_denied_servers: Set of MCP server names that are denied
        mcp_allowed_tools: Set of MCP tools in "server:tool" format that are allowed
        mcp_denied_tools: Set of MCP tools in "server:tool" format that are denied
    """

    version: int = SCHEMA_VERSION
    mode: str = "allowlist"
    allow_tools: Set[str] = field(default_factory=set)
    allow_groups: Set[str] = field(default_factory=set)
    deny_tools: Set[str] = field(default_factory=set)
    deny_groups: Set[str] = field(default_factory=set)
    shell_allowed_commands: Set[str] = field(default_factory=set)
    shell_denied_commands: Set[str] = field(default_factory=set)
    # MCP permissions
    mcp_allowed_servers: Set[str] = field(default_factory=set)
    mcp_denied_servers: Set[str] = field(default_factory=set)
    mcp_allowed_tools: Set[str] = field(default_factory=set)  # "server:tool" format
    mcp_denied_tools: Set[str] = field(default_factory=set)  # "server:tool" format

    @classmethod
    def load(cls, persona_dir: Path) -> Optional["ToolPermissions"]:
        """Load permissions from a persona directory.

        Args:
            persona_dir: Path to the persona directory (e.g., ~/.silica/personas/my_persona)

        Returns:
            ToolPermissions instance if config file exists and is valid, None otherwise.
            Returns None if file doesn't exist (meaning no tools allowed by default).
        """
        permissions_file = persona_dir / PERMISSIONS_FILE

        if not permissions_file.exists():
            return None

        try:
            with open(permissions_file, "r") as f:
                data = json.load(f)

            # Parse the JSON structure into our dataclass
            allow_section = data.get("allow", {})
            deny_section = data.get("deny", {})
            shell_section = data.get("shell_permissions", {})
            mcp_section = data.get("mcp_permissions", {})

            return cls(
                version=data.get("version", SCHEMA_VERSION),
                mode=data.get("mode", "allowlist"),
                allow_tools=set(allow_section.get("tools", [])),
                allow_groups=set(allow_section.get("groups", [])),
                deny_tools=set(deny_section.get("tools", [])),
                deny_groups=set(deny_section.get("groups", [])),
                shell_allowed_commands=set(shell_section.get("allowed_commands", [])),
                shell_denied_commands=set(shell_section.get("denied_commands", [])),
                mcp_allowed_servers=set(mcp_section.get("allowed_servers", [])),
                mcp_denied_servers=set(mcp_section.get("denied_servers", [])),
                mcp_allowed_tools=set(mcp_section.get("allowed_tools", [])),
                mcp_denied_tools=set(mcp_section.get("denied_tools", [])),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            # Invalid JSON or structure - treat as no config
            return None

    def save(self, persona_dir: Path) -> None:
        """Save permissions to a persona directory.

        Args:
            persona_dir: Path to the persona directory
        """
        permissions_file = persona_dir / PERMISSIONS_FILE

        # Ensure persona directory exists
        persona_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "version": self.version,
            "mode": self.mode,
            "allow": {
                "tools": sorted(list(self.allow_tools)),
                "groups": sorted(list(self.allow_groups)),
            },
            "deny": {
                "tools": sorted(list(self.deny_tools)),
                "groups": sorted(list(self.deny_groups)),
            },
            "shell_permissions": {
                "allowed_commands": sorted(list(self.shell_allowed_commands)),
                "denied_commands": sorted(list(self.shell_denied_commands)),
            },
            "mcp_permissions": {
                "allowed_servers": sorted(list(self.mcp_allowed_servers)),
                "denied_servers": sorted(list(self.mcp_denied_servers)),
                "allowed_tools": sorted(list(self.mcp_allowed_tools)),
                "denied_tools": sorted(list(self.mcp_denied_tools)),
            },
        }

        with open(permissions_file, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")  # Trailing newline for prettier diffs

    def is_tool_allowed(self, tool_name: str, group: Optional[str] = None) -> bool:
        """Check if a tool is allowed based on current permissions.

        Args:
            tool_name: Name of the tool
            group: Optional group the tool belongs to

        Returns:
            True if the tool is allowed, False otherwise.

        Resolution logic:
            Allowlist mode:
                1. Tool must be in allow_tools OR its group must be in allow_groups
                2. Then check deny lists - if in deny_tools or group in deny_groups, deny

            Denylist mode:
                1. Tool is allowed unless in deny_tools OR its group in deny_groups
                2. Allow lists are ignored in this mode
        """
        if self.mode == "allowlist":
            # Must be explicitly allowed first
            is_allowed = tool_name in self.allow_tools or (
                group is not None and group in self.allow_groups
            )

            if not is_allowed:
                return False

            # Then check deny list for exceptions
            is_denied = tool_name in self.deny_tools or (
                group is not None and group in self.deny_groups
            )

            return not is_denied

        else:  # denylist mode
            # Allowed unless explicitly denied
            is_denied = tool_name in self.deny_tools or (
                group is not None and group in self.deny_groups
            )

            return not is_denied

    def is_mcp_tool_allowed(self, server_name: str, tool_name: str) -> bool:
        """Check if an MCP tool is allowed based on current permissions.

        Args:
            server_name: Name of the MCP server
            tool_name: Name of the tool on that server (original name, not prefixed)

        Returns:
            True if the MCP tool is allowed, False otherwise.

        Resolution logic:
            Allowlist mode:
                1. Server must be in mcp_allowed_servers OR tool in mcp_allowed_tools
                2. Then check deny lists

            Denylist mode:
                1. Tool is allowed unless server in mcp_denied_servers OR tool in mcp_denied_tools

        The mcp_allowed_tools and mcp_denied_tools use "server:tool" format for
        granular per-tool control.
        """
        tool_key = f"{server_name}:{tool_name}"

        if self.mode == "allowlist":
            # Must be explicitly allowed first
            is_allowed = (
                server_name in self.mcp_allowed_servers
                or tool_key in self.mcp_allowed_tools
            )

            if not is_allowed:
                return False

            # Then check deny list for exceptions
            is_denied = (
                server_name in self.mcp_denied_servers
                or tool_key in self.mcp_denied_tools
            )

            return not is_denied

        else:  # denylist mode
            # Allowed unless explicitly denied
            is_denied = (
                server_name in self.mcp_denied_servers
                or tool_key in self.mcp_denied_tools
            )

            return not is_denied

    def is_mcp_server_allowed(self, server_name: str) -> bool:
        """Check if an MCP server is allowed (can connect at all).

        Args:
            server_name: Name of the MCP server

        Returns:
            True if the server is allowed to connect.

        Note: Even if a server is allowed, individual tools may still be denied.
        """
        if self.mode == "allowlist":
            # Server must be in allowed list or have any tools in allowed_tools
            is_allowed = server_name in self.mcp_allowed_servers or any(
                t.startswith(f"{server_name}:") for t in self.mcp_allowed_tools
            )
            if not is_allowed:
                return False

            # Check if server is in deny list
            return server_name not in self.mcp_denied_servers

        else:  # denylist mode
            return server_name not in self.mcp_denied_servers


class PermissionsManager:
    """Manages tool permissions for a persona.

    This class provides methods to filter tools based on permissions and
    mutate the permission configuration.

    Attributes:
        persona_dir: Path to the persona directory
        dwr_mode: If True, bypass all permissions (Danger Will Robinson mode)
        permissions: The loaded ToolPermissions, or None if no config exists
    """

    def __init__(self, persona_dir: Path, dwr_mode: bool = False):
        """Initialize the permissions manager.

        Args:
            persona_dir: Path to the persona directory
            dwr_mode: If True, bypass all permissions
        """
        self.persona_dir = persona_dir
        self.dwr_mode = dwr_mode

        if dwr_mode:
            # DWR mode bypasses all permissions
            self.permissions = None
        else:
            self.permissions = ToolPermissions.load(persona_dir)

    def filter_tools(self, tools: List[Callable]) -> List[Callable]:
        """Filter built-in tools based on permissions.

        Args:
            tools: List of tool functions decorated with @tool

        Returns:
            Filtered list of tools that are allowed.
            If dwr_mode is True, returns all tools.
            If no permissions file exists, returns empty list.
        """
        if self.dwr_mode:
            return tools

        if self.permissions is None:
            return []

        from .framework import get_tool_group

        return [
            tool
            for tool in tools
            if self.permissions.is_tool_allowed(tool.__name__, get_tool_group(tool))
        ]

    def filter_user_tools(
        self, tools: Dict[str, "DiscoveredTool"]
    ) -> Dict[str, "DiscoveredTool"]:
        """Filter user tools based on permissions.

        Args:
            tools: Dictionary of tool name to DiscoveredTool

        Returns:
            Filtered dictionary of tools that are allowed.
            If dwr_mode is True, returns all tools.
            If no permissions file exists, returns empty dict.
        """
        if self.dwr_mode:
            return tools

        if self.permissions is None:
            return {}

        return {
            name: tool
            for name, tool in tools.items()
            if self.permissions.is_tool_allowed(
                name, getattr(tool, "group", tool.file_stem)
            )
        }

    def add_to_allow(
        self, tool_name: Optional[str] = None, group: Optional[str] = None
    ) -> None:
        """Add a tool or group to the allow list.

        Args:
            tool_name: Name of tool to add (optional)
            group: Name of group to add (optional)
        """
        if self.permissions is None:
            # Create new permissions with allowlist mode
            self.permissions = ToolPermissions(mode="allowlist")

        if tool_name:
            self.permissions.allow_tools.add(tool_name)

        if group:
            self.permissions.allow_groups.add(group)

    def add_to_deny(
        self, tool_name: Optional[str] = None, group: Optional[str] = None
    ) -> None:
        """Add a tool or group to the deny list.

        Args:
            tool_name: Name of tool to add (optional)
            group: Name of group to add (optional)
        """
        if self.permissions is None:
            # Create new permissions with denylist mode
            self.permissions = ToolPermissions(mode="denylist")

        if tool_name:
            self.permissions.deny_tools.add(tool_name)

        if group:
            self.permissions.deny_groups.add(group)

    def remove_from_allow(
        self, tool_name: Optional[str] = None, group: Optional[str] = None
    ) -> None:
        """Remove a tool or group from the allow list.

        Args:
            tool_name: Name of tool to remove (optional)
            group: Name of group to remove (optional)
        """
        if self.permissions is None:
            return

        if tool_name:
            self.permissions.allow_tools.discard(tool_name)

        if group:
            self.permissions.allow_groups.discard(group)

    def remove_from_deny(
        self, tool_name: Optional[str] = None, group: Optional[str] = None
    ) -> None:
        """Remove a tool or group from the deny list.

        Args:
            tool_name: Name of tool to remove (optional)
            group: Name of group to remove (optional)
        """
        if self.permissions is None:
            return

        if tool_name:
            self.permissions.deny_tools.discard(tool_name)

        if group:
            self.permissions.deny_groups.discard(group)

    def set_mode(self, mode: str) -> None:
        """Set the permission mode.

        Args:
            mode: Must be "allowlist" or "denylist"

        Raises:
            ValueError: If mode is not valid
        """
        if mode not in ("allowlist", "denylist"):
            raise ValueError(f"Invalid mode: {mode}. Must be 'allowlist' or 'denylist'")

        if self.permissions is None:
            self.permissions = ToolPermissions(mode=mode)
        else:
            self.permissions.mode = mode

    def add_shell_command(self, command: str, allow: bool = True) -> None:
        """Add a shell command to the allow or deny list.

        Args:
            command: The shell command name to add
            allow: If True, add to allow list; if False, add to deny list
        """
        if self.permissions is None:
            self.permissions = ToolPermissions()

        if allow:
            self.permissions.shell_allowed_commands.add(command)
        else:
            self.permissions.shell_denied_commands.add(command)

    def remove_shell_command(self, command: str, from_allow: bool = True) -> None:
        """Remove a shell command from the allow or deny list.

        Args:
            command: The shell command name to remove
            from_allow: If True, remove from allow list; if False, remove from deny list
        """
        if self.permissions is None:
            return

        if from_allow:
            self.permissions.shell_allowed_commands.discard(command)
        else:
            self.permissions.shell_denied_commands.discard(command)

    def filter_mcp_tools(self, tools: List[dict], server_name: str) -> List[dict]:
        """Filter MCP tools from a server based on permissions.

        Args:
            tools: List of Anthropic-format tool schemas from an MCP server
            server_name: Name of the MCP server these tools come from

        Returns:
            Filtered list of tool schemas that are allowed.
            If dwr_mode is True, returns all tools.
            If no permissions file exists, returns empty list.
        """
        if self.dwr_mode:
            return tools

        if self.permissions is None:
            return []

        from silica.developer.mcp.schema import unprefix_tool_name

        filtered = []
        for tool in tools:
            tool_name = tool.get("name", "")
            # Get original tool name by stripping the mcp_ prefix
            unprefixed = unprefix_tool_name(tool_name)
            if unprefixed is None:
                # Not a prefixed MCP tool name, skip
                continue
            parsed_server, original_name = unprefixed
            # Verify server name matches
            if parsed_server != server_name:
                continue
            if self.permissions.is_mcp_tool_allowed(server_name, original_name):
                filtered.append(tool)

        return filtered

    def is_mcp_server_allowed(self, server_name: str) -> bool:
        """Check if an MCP server is allowed to connect.

        Args:
            server_name: Name of the MCP server

        Returns:
            True if the server is allowed.
            If dwr_mode is True, always returns True.
            If no permissions file exists, returns False.
        """
        if self.dwr_mode:
            return True

        if self.permissions is None:
            return False

        return self.permissions.is_mcp_server_allowed(server_name)

    def add_mcp_server(self, server_name: str, allow: bool = True) -> None:
        """Add an MCP server to the allow or deny list.

        Args:
            server_name: Name of the MCP server
            allow: If True, add to allow list; if False, add to deny list
        """
        if self.permissions is None:
            self.permissions = ToolPermissions()

        if allow:
            self.permissions.mcp_allowed_servers.add(server_name)
        else:
            self.permissions.mcp_denied_servers.add(server_name)

    def remove_mcp_server(self, server_name: str, from_allow: bool = True) -> None:
        """Remove an MCP server from the allow or deny list.

        Args:
            server_name: Name of the MCP server
            from_allow: If True, remove from allow list; if False, remove from deny list
        """
        if self.permissions is None:
            return

        if from_allow:
            self.permissions.mcp_allowed_servers.discard(server_name)
        else:
            self.permissions.mcp_denied_servers.discard(server_name)

    def add_mcp_tool(
        self, server_name: str, tool_name: str, allow: bool = True
    ) -> None:
        """Add a specific MCP tool to the allow or deny list.

        Args:
            server_name: Name of the MCP server
            tool_name: Name of the tool (original name, not prefixed)
            allow: If True, add to allow list; if False, add to deny list
        """
        if self.permissions is None:
            self.permissions = ToolPermissions()

        tool_key = f"{server_name}:{tool_name}"
        if allow:
            self.permissions.mcp_allowed_tools.add(tool_key)
        else:
            self.permissions.mcp_denied_tools.add(tool_key)

    def remove_mcp_tool(
        self, server_name: str, tool_name: str, from_allow: bool = True
    ) -> None:
        """Remove a specific MCP tool from the allow or deny list.

        Args:
            server_name: Name of the MCP server
            tool_name: Name of the tool (original name, not prefixed)
            from_allow: If True, remove from allow list; if False, remove from deny list
        """
        if self.permissions is None:
            return

        tool_key = f"{server_name}:{tool_name}"
        if from_allow:
            self.permissions.mcp_allowed_tools.discard(tool_key)
        else:
            self.permissions.mcp_denied_tools.discard(tool_key)

    def save(self) -> None:
        """Save the current permissions to disk."""
        if self.permissions is not None:
            self.permissions.save(self.persona_dir)
