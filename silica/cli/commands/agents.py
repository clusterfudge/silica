"""Agent management commands for silica."""

import click
from rich.console import Console
from rich.table import Table

from silica.utils.yaml_agents import get_supported_agents
from silica.utils.agent_yaml import load_agent_config

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
    console.print("\n[dim]Use 'si status -w <workspace>' to see agent configuration for specific workspaces[/dim]")


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