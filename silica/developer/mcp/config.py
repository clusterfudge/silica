"""Configuration loading and validation for MCP servers.

Supports loading MCP server configurations from:
1. Global: ~/.silica/mcp_servers.json
2. Per-persona: ~/.silica/personas/{persona}/mcp_servers.json
3. Per-project: {project_root}/.silica/mcp_servers.json

Configurations are merged with project > persona > global precedence.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["MCPConfig", "MCPServerConfig", "MCPAuthConfig", "load_mcp_config"]


@dataclass
class MCPAuthConfig:
    """Authentication configuration for an MCP server."""

    type: str  # "oauth", "api_key", "custom"
    scopes: list[str] = field(default_factory=list)
    credentials_file: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    # Additional auth-specific fields can be added via extra
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    cache: bool = True  # Whether to cache tool schemas
    auth: MCPAuthConfig | None = None


@dataclass
class MCPConfig:
    """Complete MCP configuration with all servers."""

    servers: dict[str, MCPServerConfig] = field(default_factory=dict)

    def get_enabled_servers(self) -> dict[str, MCPServerConfig]:
        """Return only enabled servers."""
        return {name: cfg for name, cfg in self.servers.items() if cfg.enabled}


def load_mcp_config(
    project_root: Path | None = None,
    persona: str | None = None,
    silica_dir: Path | None = None,
) -> MCPConfig:
    """Load and merge MCP configuration from all sources.

    Args:
        project_root: Project directory for project-specific config
        persona: Persona name for persona-specific config
        silica_dir: Override for ~/.silica directory (for testing)

    Returns:
        Merged MCPConfig with project > persona > global precedence
    """
    # Implementation will be added in task c1c72d5b
    raise NotImplementedError("MCPConfig loading not yet implemented")
