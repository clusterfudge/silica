"""Agent management commands for silica."""

import click
from rich.console import Console
from rich.table import Table

from silica.config import find_git_root, get_silica_dir
from silica.utils.yaml_agents import get_supported_agents
from silica.utils.agent_yaml import load_agent_config
from silica.config.multi_workspace import list_workspaces

console = Console()


@click.group()
def agents():
    """Manage agent types and configurations."""


@agents.command("list")
def list_agents():
    """List all supported agent types."""
    console.print("[bold]Available Agent Types:[/bold]")

    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Default Args", style="magenta")

    for agent_name in get_supported_agents():
        agent_config = load_agent_config(agent_name)
        if agent_config:
            # Format default arguments
            defaults_str = (
                " ".join(agent_config.default_args)
                if agent_config.default_args
                else "[dim]none[/dim]"
            )

            table.add_row(
                agent_config.name,
                agent_config.description,
                defaults_str,
            )

    console.print(table)


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
        from silica.config.multi_workspace import get_workspace_config

        config = get_workspace_config(silica_dir, workspace)

        # Get actual workspace name (in case None was passed)
        if workspace is None:
            from silica.config.multi_workspace import get_default_workspace

            workspace = get_default_workspace(silica_dir)

        # Show current agent configuration
        agent_type = config.get("agent_type", "hdev")

        console.print(f"[bold]Agent Configuration for Workspace '{workspace}':[/bold]")
        console.print(f"Agent Type: [cyan]{agent_type}[/cyan]")

        # Show agent details
        agent_details = load_agent_config(agent_type)
        if agent_details:
            console.print(f"Description: [white]{agent_details.description}[/white]")
            console.print(f"Command: [green]{agent_details.launch_command}[/green]")
            console.print(
                f"Dependencies: [yellow]{', '.join(agent_details.dependencies)}[/yellow]"
            )

            # Show default configuration from agent definition
            if agent_details.default_args:
                console.print(
                    f"Default args: [blue]{' '.join(agent_details.default_args)}[/blue]"
                )

            # Show environment variable status
            from silica.utils.agent_yaml import report_environment_status

            console.print("\n[bold]Environment Variables:[/bold]")
            report_environment_status(agent_details)

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
            agent_details = load_agent_config(agent_type)
            description = (
                agent_details.description if agent_details else "Unknown agent"
            )

            table.add_row(name, is_default, agent_type, description)

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@agents.command("set-default")
@click.argument(
    "agent_type", type=click.Choice(get_supported_agents(), case_sensitive=False)
)
def set_default_agent(agent_type):
    """Set the global default agent type for new workspaces."""
    from silica.config import set_config_value

    set_config_value("default_agent", agent_type)
    console.print(f"[green]Global default agent set to: {agent_type}[/green]")
    console.print(
        "[dim]This will be used for new workspaces created without specifying -a/--agent[/dim]"
    )


@agents.command("get-default")
def get_default_agent():
    """Show the current global default agent type."""
    from silica.config import get_config_value

    default_agent = get_config_value("default_agent", "hdev")
    console.print(f"[bold]Global default agent:[/bold] [cyan]{default_agent}[/cyan]")

    agent_details = load_agent_config(default_agent)
    if agent_details:
        console.print(f"Description: [white]{agent_details.description}[/white]")
        console.print(f"Command: [green]{agent_details.launch_command}[/green]")
