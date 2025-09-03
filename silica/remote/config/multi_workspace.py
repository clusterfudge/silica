"""Multi-workspace configuration management for silica."""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List

from silica.remote.config import DEFAULT_CONFIG
from silica.remote.utils.agents import get_default_workspace_agent_config


def load_project_config(silica_dir: Path) -> Dict[str, Any]:
    """Load the per-project configuration file with workspace support.

    Args:
        silica_dir: Path to the .silica directory

    Returns:
        Dictionary containing the project configuration with workspace support
    """
    config_file = silica_dir / "config.yaml"

    if not config_file.exists():
        # No config file yet - return an empty configuration structure
        # Let the caller decide whether to create default workspaces
        return {
            "default_workspace": "agent",  # Still default to "agent" as name
            "workspaces": {},  # But don't create any workspace entries
        }

    with open(config_file, "r") as f:
        config = yaml.safe_load(f) or {}

    # Detect old format (non-nested) and migrate
    if "workspaces" not in config:
        # This is the old format, migrate it
        old_workspace_name = config.get("workspace_name", "agent")
        migrated_config = {
            "default_workspace": old_workspace_name,
            "workspaces": {
                old_workspace_name: {
                    "piku_connection": config.get(
                        "piku_connection", DEFAULT_CONFIG["piku_connection"]
                    ),
                    "app_name": config.get("app_name", None),
                    "branch": config.get("branch", "main"),
                }
            },
        }
        # Save the migrated config
        save_project_config(silica_dir, migrated_config)
        return migrated_config

    return config


def save_project_config(silica_dir: Path, config: Dict[str, Any]) -> None:
    """Save the per-project configuration file with workspace support.

    Args:
        silica_dir: Path to the .silica directory
        config: Project configuration with workspace support
    """
    silica_dir.mkdir(parents=True, exist_ok=True)
    config_file = silica_dir / "config.yaml"

    with open(config_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def get_workspace_config(
    silica_dir: Path, workspace_name: Optional[str] = None
) -> Dict[str, Any]:
    """Get configuration for a specific workspace.

    Args:
        silica_dir: Path to the .silica directory
        workspace_name: Name of the workspace to get configuration for.
                       If None, the default workspace will be used.

    Returns:
        Dictionary containing the workspace-specific configuration
    """
    config = load_project_config(silica_dir)

    # If workspace_name not provided, use the default
    if workspace_name is None:
        workspace_name = config.get("default_workspace", "agent")

    # Ensure workspaces key exists
    if "workspaces" not in config:
        config["workspaces"] = {}

    # If the workspace doesn't exist, create it with defaults
    if workspace_name not in config["workspaces"]:
        # Only auto-create a workspace if it's explicitly requested
        # or if it's the default workspace name and no workspaces exist
        if workspace_name is not None or len(config["workspaces"]) == 0:
            # Create default workspace configuration with agent settings
            # Use the default silica developer agent configuration
            default_agent_config = get_default_workspace_agent_config()
            config["workspaces"][workspace_name] = {
                "piku_connection": DEFAULT_CONFIG["piku_connection"],
                "branch": "main",
                **default_agent_config,
            }
            save_project_config(silica_dir, config)

    return config["workspaces"][workspace_name]


def set_workspace_config(
    silica_dir: Path, workspace_name: str, workspace_config: Dict[str, Any]
) -> None:
    """Set configuration for a specific workspace.

    Args:
        silica_dir: Path to the .silica directory
        workspace_name: Name of the workspace to set configuration for
        workspace_config: Workspace-specific configuration
    """
    config = load_project_config(silica_dir)

    # Ensure workspaces key exists
    if "workspaces" not in config:
        config["workspaces"] = {}

    # Update the workspace configuration
    config["workspaces"][workspace_name] = workspace_config

    # Save the updated configuration
    save_project_config(silica_dir, config)


def get_default_workspace(silica_dir: Path) -> str:
    """Get the default workspace name for this project.

    Args:
        silica_dir: Path to the .silica directory

    Returns:
        Name of the default workspace
    """
    config = load_project_config(silica_dir)
    return config.get("default_workspace", "agent")


def set_default_workspace(silica_dir: Path, workspace_name: str) -> None:
    """Set the default workspace for this project.

    Args:
        silica_dir: Path to the .silica directory
        workspace_name: Name of the workspace to set as default
    """
    config = load_project_config(silica_dir)

    # Ensure the workspace exists before setting it as default
    if "workspaces" in config and workspace_name in config["workspaces"]:
        config["default_workspace"] = workspace_name
        save_project_config(silica_dir, config)
    else:
        raise ValueError(f"Workspace '{workspace_name}' does not exist")


def list_workspaces(silica_dir: Path) -> List[Dict[str, Any]]:
    """List all configured workspaces for this project.

    Args:
        silica_dir: Path to the .silica directory

    Returns:
        List of workspace information dictionaries with name and details
    """
    config = load_project_config(silica_dir)
    default_workspace = config.get("default_workspace", "agent")

    workspaces = []
    if "workspaces" in config:
        for name, workspace_config in config["workspaces"].items():
            workspaces.append(
                {
                    "name": name,
                    "is_default": name == default_workspace,
                    "config": workspace_config,
                }
            )

    return workspaces


def is_local_workspace_for_cleanup(
    silica_dir: Path, workspace_name: Optional[str] = None
) -> bool:
    """Check if a workspace is local (for cleanup purposes only).

    Args:
        silica_dir: Path to the .silica directory
        workspace_name: Name of the workspace to check.
                       If None, the default workspace will be used.

    Returns:
        True if the workspace is local and needs local cleanup, False otherwise
    """
    workspace_config = get_workspace_config(silica_dir, workspace_name)
    return workspace_config.get("is_local", False)


def create_workspace_config(
    silica_dir: Path, workspace_name: str, url: str, is_local: bool = False
) -> None:
    """Create a workspace configuration with the antennae URL.

    Args:
        silica_dir: Path to the .silica directory
        workspace_name: Name of the workspace to configure
        url: URL where the antennae webapp will be accessible
        is_local: Whether this is a local workspace (for cleanup purposes)
    """
    # Get current workspace config
    workspace_config = get_workspace_config(silica_dir, workspace_name)

    # Set app_name and URL - these are the only things we need
    workspace_config["app_name"] = workspace_name
    workspace_config["url"] = url

    # Only store is_local flag for cleanup purposes
    if is_local:
        workspace_config["is_local"] = True
    elif "is_local" in workspace_config:
        del workspace_config["is_local"]

    # Save updated config
    set_workspace_config(silica_dir, workspace_name, workspace_config)
