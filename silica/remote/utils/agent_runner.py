#!/usr/bin/env python3
"""Agent runner script that replaces AGENT.sh template.

This script:
1. Reads the workspace configuration to determine which agent to run
2. Loads the agent's YAML configuration
3. Ensures the agent is installed
4. Launches the agent with proper configuration
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, Any

# Add silica to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from .agent_yaml import generate_launch_command
from silica.remote.config.multi_workspace import load_project_config
from rich.console import Console

console = Console()


def load_environment_variables():
    """Load environment variables from piku ENV and LIVE_ENV files."""
    top_dir = Path.cwd()
    app_name = top_dir.name

    # Load both ENV and LIVE_ENV files (LIVE_ENV takes precedence)
    env_files = [
        Path.home() / ".piku" / "envs" / app_name / "ENV",
        Path.home() / ".piku" / "envs" / app_name / "LIVE_ENV",
    ]

    loaded_vars = {}

    for env_file in env_files:
        if env_file.exists():
            console.print(f"[blue]Loading environment from {env_file}[/blue]")
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        loaded_vars[key] = value
                        os.environ[key] = value
        else:
            console.print(f"[dim]Environment file not found: {env_file}[/dim]")

    if loaded_vars:
        console.print(f"[green]Loaded {len(loaded_vars)} environment variables[/green]")
        # Debug: show some non-sensitive variable names
        safe_vars = [
            k
            for k in loaded_vars.keys()
            if not any(
                sensitive in k.lower()
                for sensitive in ["key", "token", "secret", "password"]
            )
        ]
        if safe_vars:
            console.print(
                f"[dim]Variables loaded: {', '.join(safe_vars[:5])}{' ...' if len(safe_vars) > 5 else ''}[/dim]"
            )
    else:
        console.print("[yellow]No environment variables loaded[/yellow]")


def sync_dependencies():
    """Synchronize UV dependencies."""
    console.print("[blue]Synchronizing dependencies with uv...[/blue]")
    try:
        result = subprocess.run(
            ["uv", "sync"],
            capture_output=True,
            text=True,
            timeout=300,
            env=os.environ.copy(),  # Pass current environment to subprocess
        )
        if result.returncode != 0:
            console.print(f"[yellow]uv sync warning: {result.stderr}[/yellow]")
    except Exception as e:
        console.print(f"[yellow]uv sync error: {e}[/yellow]")


def resolve_agent_executable_path(agent_config, workspace_config):
    """Resolve the full path to the agent executable before changing directories.

    This allows us to install from project root (where pyproject.toml exists)
    but then run the agent from ./code directory with the resolved path.

    Returns:
        str: Full path to the executable, or the original command if resolution fails
    """
    # Handle both dictionary and AgentConfig object formats
    if isinstance(agent_config, dict):
        # Dictionary format from workspace_environment.py
        launch_data = agent_config.get("launch", {})
        base_command = launch_data.get("command", "")
        default_args = launch_data.get("default_args", [])

        command_parts = base_command.split()
        command_parts.extend(default_args)

        # Add workspace-specific configuration
        agent_settings = workspace_config.get("agent_config", {})
        command_parts.extend(agent_settings.get("flags", []))

        custom_args = agent_settings.get("args", {})
        for key, value in custom_args.items():
            if value is True:
                command_parts.append(f"--{key}")
            elif value is not False and value is not None:
                command_parts.extend([f"--{key}", str(value)])

        launch_command = " ".join(command_parts)
    else:
        # AgentConfig object format from agent_yaml.py
        launch_command = generate_launch_command(agent_config, workspace_config)

    # Parse the command to extract the executable part
    command_parts = launch_command.split()

    if len(command_parts) < 2 or command_parts[0] != "uv" or command_parts[1] != "run":
        # If it's not a uv run command, return as-is
        return launch_command

    # For "uv run <executable> [args...]", we need to resolve the executable path
    if len(command_parts) < 3:
        return launch_command

    executable = command_parts[2]

    try:
        # Use uv to find the full path to the executable
        result = subprocess.run(
            ["uv", "run", "which", executable],
            capture_output=True,
            text=True,
            timeout=10,
            env=os.environ.copy(),
        )

        if result.returncode == 0:
            executable_path = result.stdout.strip()
            if executable_path and Path(executable_path).exists():
                # Return the resolved path with arguments
                resolved_command = f'"{executable_path}"'
                console.print(f"[green]Resolved executable: {executable_path}[/green]")
                return resolved_command

    except (subprocess.TimeoutExpired, subprocess.SubprocessError, Exception) as e:
        console.print(f"[yellow]Could not resolve executable path: {e}[/yellow]")

    # Fallback: try to use uv run with full command from the code directory
    # This might work if the uv environment is properly set up
    console.print("[yellow]Using fallback: uv run from code directory[/yellow]")
    return launch_command


def get_workspace_agent_config() -> tuple[str, Dict[str, Any]]:
    """Get the agent type and configuration for current workspace.

    Returns:
        Tuple of (agent_type, workspace_config)
    """
    try:
        # Try to load workspace config from current .silica directory
        from silica.remote.config import get_silica_dir

        silica_dir = get_silica_dir()
        if not silica_dir or not silica_dir.exists():
            raise Exception("No .silica directory found")
        workspace_config = load_project_config(silica_dir)

        # Get current workspace name from environment or default
        current_workspace = os.environ.get(
            "SILICA_WORKSPACE_NAME", workspace_config.get("default_workspace", "agent")
        )

        if current_workspace in workspace_config.get("workspaces", {}):
            ws_config = workspace_config["workspaces"][current_workspace]
            agent_type = ws_config.get("agent_type", "hdev")
            return agent_type, ws_config
        else:
            console.print(
                f"[yellow]Workspace '{current_workspace}' not found, using default[/yellow]"
            )
            return "hdev", {
                "agent_type": "hdev",
                "agent_config": {"flags": [], "args": {}},
            }

    except Exception as e:
        console.print(f"[yellow]Error loading workspace config: {e}[/yellow]")
        console.print("[yellow]Using default agent configuration[/yellow]")
        return "hdev", {"agent_type": "hdev", "agent_config": {"flags": [], "args": {}}}
