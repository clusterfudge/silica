"""Configuration handling for antennae webapp.

Manages workspace configuration and environment variables for a single workspace
managed by this antennae instance.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional


class AntennaeConfig:
    """Configuration manager for antennae webapp."""

    def __init__(self):
        """Initialize configuration from environment."""
        self.working_directory = Path.cwd()

    def get_workspace_name_from_env(self) -> str:
        """Get workspace name from environment (dynamic)."""
        return os.environ.get("WORKSPACE_NAME", "agent")

    @property
    def code_directory(self) -> Path:
        """Get code directory path (dynamic)."""
        return self.working_directory / "code"

    def get_workspace_name(self) -> str:
        """Get the workspace name for this antennae instance."""
        return self.get_workspace_name_from_env()

    def get_code_directory(self) -> Path:
        """Get the code directory path."""
        return self.code_directory

    def get_working_directory(self) -> Path:
        """Get the antennae working directory."""
        return self.working_directory

    def get_tmux_session_name(self) -> str:
        """Get the tmux session name for this workspace."""
        # Use workspace name with -agent suffix to avoid collision with antennae server session
        return f"{self.get_workspace_name_from_env()}-agent"

    def get_agent_command(
        self, workspace_config: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate the silica developer command for this workspace.

        Args:
            workspace_config: Optional workspace-specific configuration

        Returns:
            Command string to execute silica developer
        """
        # Import here to avoid circular dependency
        from silica.remote.utils.agents import generate_agent_command

        # Use provided config or load from file
        if workspace_config is None:
            workspace_config = self.load_workspace_config()

        return generate_agent_command(workspace_config)

    def load_workspace_config(self) -> Dict[str, Any]:
        """Load workspace configuration from file.

        Returns:
            Workspace configuration dictionary
        """
        config_file = self.working_directory / "workspace_config.json"

        if config_file.exists():
            with open(config_file, "r") as f:
                return json.load(f)
        else:
            # Return default configuration
            from silica.remote.utils.agents import get_default_workspace_agent_config

            return get_default_workspace_agent_config()

    def save_workspace_config(self, config: Dict[str, Any]) -> None:
        """Save workspace configuration to file.

        Args:
            config: Workspace configuration to save
        """
        config_file = self.working_directory / "workspace_config.json"

        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)

    def ensure_code_directory(self) -> None:
        """Ensure the code directory exists."""
        self.code_directory.mkdir(exist_ok=True)


# Global config instance
config = AntennaeConfig()
