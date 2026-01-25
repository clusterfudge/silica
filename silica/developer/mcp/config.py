"""Configuration loading and validation for MCP servers.

Supports loading MCP server configurations from:
1. Global: ~/.silica/mcp_servers.json
2. Per-persona: ~/.silica/personas/{persona}/mcp_servers.json
3. Per-project: {project_root}/.silica/mcp_servers.json

Configurations are merged with project > persona > global precedence.
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "MCPConfig",
    "MCPServerConfig",
    "MCPAuthConfig",
    "load_mcp_config",
    "expand_env_vars",
]


# Pattern to match ${VAR} or ${VAR:-default} syntax
ENV_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


def expand_env_vars(value: str) -> str:
    """Expand environment variables in a string.

    Supports:
    - ${VAR} - replaced with env var value, empty string if not set
    - ${VAR:-default} - replaced with env var value, or default if not set

    Args:
        value: String potentially containing ${VAR} patterns.

    Returns:
        String with environment variables expanded.
    """

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2)  # May be None if no default specified
        env_value = os.environ.get(var_name)
        if env_value is not None:
            return env_value
        return default if default is not None else ""

    return ENV_VAR_PATTERN.sub(replacer, value)


def expand_env_vars_recursive(obj: Any) -> Any:
    """Recursively expand environment variables in a data structure.

    Args:
        obj: Dictionary, list, or string to process.

    Returns:
        Object with all string values having env vars expanded.
    """
    if isinstance(obj, str):
        return expand_env_vars(obj)
    elif isinstance(obj, dict):
        return {k: expand_env_vars_recursive(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [expand_env_vars_recursive(item) for item in obj]
    return obj


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPAuthConfig":
        """Create MCPAuthConfig from a dictionary."""
        known_fields = {
            "type",
            "scopes",
            "credentials_file",
            "client_id",
            "client_secret",
        }
        extra = {k: v for k, v in data.items() if k not in known_fields}
        return cls(
            type=data.get("type", "api_key"),
            scopes=data.get("scopes", []),
            credentials_file=data.get("credentials_file"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            extra=extra,
        )


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

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "MCPServerConfig":
        """Create MCPServerConfig from a dictionary.

        Args:
            name: Server name (from the config key).
            data: Server configuration dictionary.

        Returns:
            MCPServerConfig instance.
        """
        auth_data = data.get("auth")
        auth = MCPAuthConfig.from_dict(auth_data) if auth_data else None

        return cls(
            name=name,
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            enabled=data.get("enabled", True),
            cache=data.get("cache", True),
            auth=auth,
        )


@dataclass
class MCPConfig:
    """Complete MCP configuration with all servers."""

    servers: dict[str, MCPServerConfig] = field(default_factory=dict)

    def get_enabled_servers(self) -> dict[str, MCPServerConfig]:
        """Return only enabled servers."""
        return {name: cfg for name, cfg in self.servers.items() if cfg.enabled}

    def merge_with(self, other: "MCPConfig") -> "MCPConfig":
        """Merge another config into this one.

        The other config takes precedence (overwrites this config's values).

        Args:
            other: Config to merge in (higher precedence).

        Returns:
            New merged MCPConfig.
        """
        merged_servers = dict(self.servers)
        merged_servers.update(other.servers)
        return MCPConfig(servers=merged_servers)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPConfig":
        """Create MCPConfig from a dictionary.

        Args:
            data: Configuration dictionary with 'servers' key.

        Returns:
            MCPConfig instance.
        """
        servers_data = data.get("servers", {})
        servers = {
            name: MCPServerConfig.from_dict(name, config)
            for name, config in servers_data.items()
        }
        return cls(servers=servers)

    @classmethod
    def from_file(cls, path: Path) -> "MCPConfig":
        """Load MCPConfig from a JSON file.

        Environment variables in the form ${VAR} are expanded.

        Args:
            path: Path to the JSON config file.

        Returns:
            MCPConfig instance.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            json.JSONDecodeError: If the file contains invalid JSON.
        """
        with open(path) as f:
            data = json.load(f)
        # Expand environment variables in the loaded data
        data = expand_env_vars_recursive(data)
        return cls.from_dict(data)


def get_default_silica_dir() -> Path:
    """Get the default ~/.silica directory."""
    return Path.home() / ".silica"


def load_mcp_config(
    project_root: Path | None = None,
    persona: str | None = None,
    silica_dir: Path | None = None,
) -> MCPConfig:
    """Load and merge MCP configuration from all sources.

    Loads configuration files from (in order of increasing precedence):
    1. Global: ~/.silica/mcp_servers.json
    2. Per-persona: ~/.silica/personas/{persona}/mcp_servers.json
    3. Per-project: {project_root}/.silica/mcp_servers.json

    Args:
        project_root: Project directory for project-specific config.
        persona: Persona name for persona-specific config.
        silica_dir: Override for ~/.silica directory (for testing).

    Returns:
        Merged MCPConfig with project > persona > global precedence.
    """
    if silica_dir is None:
        silica_dir = get_default_silica_dir()

    config = MCPConfig()

    # 1. Load global config (lowest precedence)
    global_path = silica_dir / "mcp_servers.json"
    if global_path.exists():
        try:
            config = config.merge_with(MCPConfig.from_file(global_path))
        except (json.JSONDecodeError, KeyError) as e:
            # Log warning but continue - don't fail on bad config
            import logging

            logging.warning(f"Failed to load global MCP config from {global_path}: {e}")

    # 2. Load persona config (medium precedence)
    if persona:
        persona_path = silica_dir / "personas" / persona / "mcp_servers.json"
        if persona_path.exists():
            try:
                config = config.merge_with(MCPConfig.from_file(persona_path))
            except (json.JSONDecodeError, KeyError) as e:
                import logging

                logging.warning(
                    f"Failed to load persona MCP config from {persona_path}: {e}"
                )

    # 3. Load project config (highest precedence)
    if project_root:
        project_path = project_root / ".silica" / "mcp_servers.json"
        if project_path.exists():
            try:
                config = config.merge_with(MCPConfig.from_file(project_path))
            except (json.JSONDecodeError, KeyError) as e:
                import logging

                logging.warning(
                    f"Failed to load project MCP config from {project_path}: {e}"
                )

    return config
