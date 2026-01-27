"""Configuration loading and validation for MCP servers.

Supports loading MCP server configurations from:
1. Global: ~/.silica/mcp_servers.json
2. Per-persona: ~/.silica/personas/{persona}/mcp_servers.json
3. Per-project: {project_root}/.silica/mcp_servers.json

Configurations are merged with project > persona > global precedence.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "MCPConfig",
    "MCPServerConfig",
    "load_mcp_config",
    "save_mcp_config",
    "add_mcp_server",
    "remove_mcp_server",
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
class MCPServerConfig:
    """Configuration for a single MCP server.

    Attributes:
        name: Server identifier.
        command: Command to run the server.
        args: Arguments to pass to the command.
        env: Environment variables for the server process.
        enabled: Whether to auto-connect at startup.
        cache: Whether to cache tool schemas.
        setup_command: Optional command to run server's auth/setup flow.
        credentials_path: Optional path where server stores credentials.
    """

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    cache: bool = True
    # Optional: command to run for interactive setup (e.g., auth flow)
    setup_command: str | None = None
    setup_args: list[str] = field(default_factory=list)
    # Optional: path to check if credentials exist
    credentials_path: str | None = None

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "MCPServerConfig":
        """Create MCPServerConfig from a dictionary.

        Args:
            name: Server name (from the config key).
            data: Server configuration dictionary.

        Returns:
            MCPServerConfig instance.
        """
        return cls(
            name=name,
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            enabled=data.get("enabled", True),
            cache=data.get("cache", True),
            setup_command=data.get("setup_command"),
            setup_args=data.get("setup_args", []),
            credentials_path=data.get("credentials_path"),
        )

    def needs_setup(self) -> bool:
        """Check if this server needs setup (credentials don't exist).

        Returns:
            True if credentials_path is specified but doesn't exist.
            False if no credentials_path or if credentials exist.
        """
        if not self.credentials_path:
            return False
        path = Path(expand_env_vars(self.credentials_path))
        return not path.exists()

    def has_setup_command(self) -> bool:
        """Check if this server has a setup command configured."""
        return bool(self.setup_command)


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
            logging.warning(f"Failed to load global MCP config from {global_path}: {e}")

    # 2. Load persona config (medium precedence)
    if persona:
        persona_path = silica_dir / "personas" / persona / "mcp_servers.json"
        if persona_path.exists():
            try:
                config = config.merge_with(MCPConfig.from_file(persona_path))
            except (json.JSONDecodeError, KeyError) as e:
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
                logging.warning(
                    f"Failed to load project MCP config from {project_path}: {e}"
                )

    return config


def save_mcp_config(
    config: MCPConfig,
    location: str = "global",
    project_root: Path | None = None,
    persona: str | None = None,
    silica_dir: Path | None = None,
) -> Path:
    """Save MCP configuration to a JSON file.

    Args:
        config: MCPConfig to save.
        location: Where to save - "global", "persona", or "project".
        project_root: Required if location is "project".
        persona: Required if location is "persona".
        silica_dir: Override for ~/.silica directory (for testing).

    Returns:
        Path where config was saved.

    Raises:
        ValueError: If required arguments are missing for the location.
    """
    if silica_dir is None:
        silica_dir = get_default_silica_dir()

    if location == "global":
        path = silica_dir / "mcp_servers.json"
    elif location == "persona":
        if not persona:
            raise ValueError("persona required for persona location")
        path = silica_dir / "personas" / persona / "mcp_servers.json"
    elif location == "project":
        if not project_root:
            raise ValueError("project_root required for project location")
        path = project_root / ".silica" / "mcp_servers.json"
    else:
        raise ValueError(f"Unknown location: {location}")

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Convert config to dict for JSON serialization
    data = {
        "servers": {
            name: {
                "command": srv.command,
                "args": srv.args,
                **({"env": srv.env} if srv.env else {}),
                **({"enabled": srv.enabled} if not srv.enabled else {}),
                **({"cache": srv.cache} if not srv.cache else {}),
                **({"setup_command": srv.setup_command} if srv.setup_command else {}),
                **({"setup_args": srv.setup_args} if srv.setup_args else {}),
                **(
                    {"credentials_path": srv.credentials_path}
                    if srv.credentials_path
                    else {}
                ),
            }
            for name, srv in config.servers.items()
        }
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    return path


def add_mcp_server(
    name: str,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    enabled: bool = True,
    location: str = "global",
    project_root: Path | None = None,
    persona: str | None = None,
    silica_dir: Path | None = None,
) -> Path:
    """Add or update an MCP server in the configuration.

    Args:
        name: Server name/identifier.
        command: Command to run the server.
        args: Arguments for the command.
        env: Environment variables.
        enabled: Whether to auto-connect.
        location: Where to save - "global", "persona", or "project".
        project_root: Required if location is "project".
        persona: Required if location is "persona".
        silica_dir: Override for ~/.silica directory.

    Returns:
        Path where config was saved.
    """
    if silica_dir is None:
        silica_dir = get_default_silica_dir()

    # Load existing config for this specific location only
    if location == "global":
        path = silica_dir / "mcp_servers.json"
    elif location == "persona":
        if not persona:
            raise ValueError("persona required for persona location")
        path = silica_dir / "personas" / persona / "mcp_servers.json"
    elif location == "project":
        if not project_root:
            raise ValueError("project_root required for project location")
        path = project_root / ".silica" / "mcp_servers.json"
    else:
        raise ValueError(f"Unknown location: {location}")

    # Load existing or create empty
    if path.exists():
        try:
            config = MCPConfig.from_file(path)
        except (json.JSONDecodeError, KeyError):
            config = MCPConfig()
    else:
        config = MCPConfig()

    # Add/update server
    config.servers[name] = MCPServerConfig(
        name=name,
        command=command,
        args=args or [],
        env=env or {},
        enabled=enabled,
    )

    return save_mcp_config(
        config,
        location=location,
        project_root=project_root,
        persona=persona,
        silica_dir=silica_dir,
    )


def remove_mcp_server(
    name: str,
    location: str = "global",
    project_root: Path | None = None,
    persona: str | None = None,
    silica_dir: Path | None = None,
) -> bool:
    """Remove an MCP server from the configuration.

    Args:
        name: Server name to remove.
        location: Where to remove from - "global", "persona", or "project".
        project_root: Required if location is "project".
        persona: Required if location is "persona".
        silica_dir: Override for ~/.silica directory.

    Returns:
        True if server was removed, False if it wasn't found.
    """
    if silica_dir is None:
        silica_dir = get_default_silica_dir()

    # Determine path
    if location == "global":
        path = silica_dir / "mcp_servers.json"
    elif location == "persona":
        if not persona:
            raise ValueError("persona required for persona location")
        path = silica_dir / "personas" / persona / "mcp_servers.json"
    elif location == "project":
        if not project_root:
            raise ValueError("project_root required for project location")
        path = project_root / ".silica" / "mcp_servers.json"
    else:
        raise ValueError(f"Unknown location: {location}")

    if not path.exists():
        return False

    try:
        config = MCPConfig.from_file(path)
    except (json.JSONDecodeError, KeyError):
        return False

    if name not in config.servers:
        return False

    del config.servers[name]
    save_mcp_config(
        config,
        location=location,
        project_root=project_root,
        persona=persona,
        silica_dir=silica_dir,
    )
    return True
