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
from datetime import datetime
from typing import Dict, Any

# Add silica to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.agent_yaml import load_agent_config, install_agent, generate_launch_command
from config.multi_workspace import load_workspace_config
from rich.console import Console

console = Console()


def load_environment_variables():
    """Load environment variables from piku ENV file."""
    top_dir = Path.cwd()
    app_name = top_dir.name

    env_file = Path.home() / ".piku" / "envs" / app_name / "ENV"

    if env_file.exists():
        console.print(f"[blue]Loading environment from {env_file}[/blue]")
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value
    else:
        console.print(f"[yellow]Environment file not found: {env_file}[/yellow]")


def sync_dependencies():
    """Synchronize UV dependencies."""
    console.print("[blue]Synchronizing dependencies with uv...[/blue]")
    try:
        result = subprocess.run(
            ["uv", "sync"], capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            console.print(f"[yellow]uv sync warning: {result.stderr}[/yellow]")
    except Exception as e:
        console.print(f"[yellow]uv sync error: {e}[/yellow]")


def get_workspace_agent_config() -> tuple[str, Dict[str, Any]]:
    """Get the agent type and configuration for current workspace.

    Returns:
        Tuple of (agent_type, workspace_config)
    """
    try:
        # Try to load workspace config
        workspace_config = load_workspace_config()

        # Get current workspace name from environment or default
        current_workspace = os.environ.get("SILICA_WORKSPACE", "agent")

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


def main():
    """Main agent runner function."""
    console.print(f"[cyan]Starting agent runner at {datetime.now()}[/cyan]")

    # Get directory information
    top_dir = Path.cwd()
    app_name = top_dir.name
    console.print(f"[blue]Working directory: {top_dir}[/blue]")
    console.print(f"[blue]App name: {app_name}[/blue]")

    # Load environment variables
    load_environment_variables()

    # Sync dependencies
    sync_dependencies()

    # Change to code directory
    code_dir = top_dir / "code"
    if code_dir.exists():
        os.chdir(code_dir)
        console.print(f"[blue]Changed to code directory: {code_dir}[/blue]")
    else:
        console.print(
            f"[yellow]Code directory not found, staying in: {top_dir}[/yellow]"
        )

    # Get workspace agent configuration
    agent_type, workspace_config = get_workspace_agent_config()
    console.print(f"[green]Using agent: {agent_type}[/green]")

    # Load agent configuration from YAML
    agent_config = load_agent_config(agent_type)
    if not agent_config:
        console.print(
            f"[red]✗ Failed to load configuration for agent: {agent_type}[/red]"
        )
        console.print("[red]Available agents:[/red]")
        from utils.agent_yaml import list_built_in_agents

        for agent in list_built_in_agents():
            console.print(f"[red]  - {agent}[/red]")
        sys.exit(1)

    console.print(f"[green]Loaded agent config: {agent_config.description}[/green]")

    # Ensure agent is installed
    if not install_agent(agent_config):
        console.print(f"[red]✗ Failed to install agent: {agent_type}[/red]")
        sys.exit(1)

    # Generate launch command
    launch_command = generate_launch_command(agent_config, workspace_config)
    console.print(f"[cyan]Launch command: {launch_command}[/cyan]")

    # Launch the agent
    console.print(
        f"[green]Starting {agent_config.name} agent from {os.getcwd()} at {datetime.now()}[/green]"
    )

    try:
        # Run the agent command
        result = subprocess.run(launch_command, shell=True)
        exit_code = result.returncode

        console.print(
            f"[yellow]Agent exited with status {exit_code} at {datetime.now()}[/yellow]"
        )

        if exit_code != 0:
            console.print(
                f"[red]Agent {agent_config.name} exited with error code {exit_code}[/red]"
            )

    except KeyboardInterrupt:
        console.print(f"[yellow]Agent {agent_config.name} interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error running agent {agent_config.name}: {e}[/red]")
        sys.exit(1)

    # Keep tmux session alive for debugging
    console.print(
        "[blue]Agent process has ended. Keeping tmux session alive for debugging.[/blue]"
    )
    console.print(
        "[blue]Press Ctrl+C to exit or run 'exit' to close this session.[/blue]"
    )

    # Wait for user input to keep session alive
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        console.print("[blue]Exiting agent runner.[/blue]")


if __name__ == "__main__":
    main()
