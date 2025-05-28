"""Agent management commands for silica."""

import click
from rich.console import Console
from rich.table import Table

from silica.config import find_git_root, get_silica_dir
from silica.utils.agents import (
    get_supported_agents,
    get_agent_config,
    update_workspace_with_agent,
    generate_agent_script,
)
from silica.config.multi_workspace import (
    get_workspace_config,
    set_workspace_config,
    list_workspaces,
)

console = Console()


@click.group()
def agents():
    """Manage agent types and configurations."""


@agents.command("list")
def list_agents():
    """List all supported agent types."""
    console.print("[bold]Supported Agent Types:[/bold]")

    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Name", style="cyan")
    table.add_column("Command", style="green")
    table.add_column("Description", style="white")
    table.add_column("Dependencies", style="yellow")

    for agent_name in get_supported_agents():
        agent_config = get_agent_config(agent_name)
        if agent_config:
            deps = ", ".join(agent_config.required_dependencies)
            table.add_row(
                agent_config.name, agent_config.command, agent_config.description, deps
            )

    console.print(table)


@agents.command("set")
@click.option(
    "-w",
    "--workspace",
    help="Workspace name (default: current default workspace)",
    default=None,
)
@click.argument(
    "agent_type", type=click.Choice(get_supported_agents(), case_sensitive=False)
)
def set_agent(workspace, agent_type):
    """Set the agent type for a workspace."""
    try:
        # Find git root and silica directory
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        silica_dir = get_silica_dir(git_root)
        if not silica_dir:
            console.print("[red]Error: No silica environment found.[/red]")
            return

        # Get current workspace configuration
        current_config = get_workspace_config(silica_dir, workspace)

        # Update with new agent settings
        updated_config = update_workspace_with_agent(current_config, agent_type)

        # Get actual workspace name (in case None was passed)
        if workspace is None:
            from silica.config.multi_workspace import get_default_workspace

            workspace = get_default_workspace(silica_dir)

        # Save updated configuration
        set_workspace_config(silica_dir, workspace, updated_config)

        # Regenerate AGENT.sh script
        script_content = generate_agent_script(updated_config)

        # Write the new script to the agent-repo
        agent_repo_path = silica_dir / "agent-repo"
        if agent_repo_path.exists():
            script_path = agent_repo_path / "AGENT.sh"
            with open(script_path, "w") as f:
                f.write(script_content)

            # Set executable permissions
            script_path.chmod(script_path.stat().st_mode | 0o755)

            console.print(
                f"[green]Successfully updated workspace '{workspace}' to use agent '{agent_type}'[/green]"
            )
            console.print(
                f"[yellow]Don't forget to sync your changes: silica sync -w {workspace}[/yellow]"
            )
        else:
            console.print("[red]Error: Agent repository not found.[/red]")

    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")


@agents.command("show")
@click.option(
    "-w",
    "--workspace",
    help="Workspace name (default: current default workspace)",
    default=None,
)
def show_agent(workspace):
    """Show the current agent configuration for a workspace."""
    try:
        # Find git root and silica directory
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        silica_dir = get_silica_dir(git_root)
        if not silica_dir:
            console.print("[red]Error: No silica environment found.[/red]")
            return

        # Get workspace configuration
        config = get_workspace_config(silica_dir, workspace)

        # Get actual workspace name (in case None was passed)
        if workspace is None:
            from silica.config.multi_workspace import get_default_workspace

            workspace = get_default_workspace(silica_dir)

        # Show current agent configuration
        agent_type = config.get("agent_type", "hdev")
        agent_config = config.get("agent_config", {})

        console.print(f"[bold]Agent Configuration for Workspace '{workspace}':[/bold]")
        console.print(f"Agent Type: [cyan]{agent_type}[/cyan]")

        # Show agent details
        agent_details = get_agent_config(agent_type)
        if agent_details:
            console.print(f"Description: [white]{agent_details.description}[/white]")
            console.print(f"Command: [green]{agent_details.command}[/green]")
            console.print(
                f"Dependencies: [yellow]{', '.join(agent_details.required_dependencies)}[/yellow]"
            )

        # Show custom configuration
        if agent_config:
            console.print("\n[bold]Custom Configuration:[/bold]")
            if "flags" in agent_config:
                console.print(f"Flags: [magenta]{agent_config['flags']}[/magenta]")
            if "args" in agent_config:
                console.print(f"Arguments: [magenta]{agent_config['args']}[/magenta]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@agents.command("status")
def status():
    """Show agent configuration for all workspaces."""
    try:
        # Find git root and silica directory
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        silica_dir = get_silica_dir(git_root)
        if not silica_dir:
            console.print("[red]Error: No silica environment found.[/red]")
            return

        # Get all workspaces
        workspaces = list_workspaces(silica_dir)

        if not workspaces:
            console.print("[yellow]No workspaces found.[/yellow]")
            return

        console.print("[bold]Agent Status for All Workspaces:[/bold]")

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("Workspace", style="cyan")
        table.add_column("Default", style="green")
        table.add_column("Agent Type", style="magenta")
        table.add_column("Description", style="white")

        for workspace in workspaces:
            name = workspace["name"]
            is_default = "✓" if workspace["is_default"] else ""
            config = workspace["config"]

            agent_type = config.get("agent_type", "hdev")
            agent_details = get_agent_config(agent_type)
            description = (
                agent_details.description if agent_details else "Unknown agent"
            )

            table.add_row(name, is_default, agent_type, description)

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@agents.command("configure")
@click.option(
    "-w",
    "--workspace",
    help="Workspace name (default: current default workspace)",
    default=None,
)
@click.argument(
    "agent_type", type=click.Choice(get_supported_agents(), case_sensitive=False)
)
def configure_agent(workspace, agent_type):
    """Interactively configure an agent for a workspace with custom settings."""
    try:
        # Find git root and silica directory
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        silica_dir = get_silica_dir(git_root)
        if not silica_dir:
            console.print("[red]Error: No silica environment found.[/red]")
            return

        # Get current workspace configuration
        current_config = get_workspace_config(silica_dir, workspace)

        # Get actual workspace name (in case None was passed)
        if workspace is None:
            from silica.config.multi_workspace import get_default_workspace

            workspace = get_default_workspace(silica_dir)

        # Get agent details for configuration
        agent_details = get_agent_config(agent_type)
        if not agent_details:
            console.print(f"[red]Error: Unknown agent type: {agent_type}[/red]")
            return

        console.print(
            f"[bold]Configuring {agent_type} for workspace '{workspace}'[/bold]"
        )
        console.print(f"Description: {agent_details.description}")
        console.print(f"Default command: {agent_details.command}")
        console.print(f"Default flags: {agent_details.default_args.get('flags', [])}")

        # For now, just do basic configuration - we can enhance this later
        # Update configuration with agent type
        updated_config = update_workspace_with_agent(current_config, agent_type)

        # Save updated configuration
        set_workspace_config(silica_dir, workspace, updated_config)

        # Regenerate AGENT.sh script
        script_content = generate_agent_script(updated_config)

        # Write the new script to the agent-repo
        agent_repo_path = silica_dir / "agent-repo"
        if agent_repo_path.exists():
            script_path = agent_repo_path / "AGENT.sh"
            with open(script_path, "w") as f:
                f.write(script_content)

            # Set executable permissions
            script_path.chmod(script_path.stat().st_mode | 0o755)

            console.print(
                f"[green]Successfully configured workspace '{workspace}' with agent '{agent_type}'[/green]"
            )
            console.print(
                f"[yellow]Don't forget to sync your changes: silica sync -w {workspace}[/yellow]"
            )
        else:
            console.print("[red]Error: Agent repository not found.[/red]")

    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
