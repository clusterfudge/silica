"""Configuration command for silica."""

import click
from pathlib import Path
from rich.console import Console
from rich.table import Table

from silica.config import load_config, set_config_value, get_config_value
from silica.utils import find_env_var

console = Console()


@click.group(name="config")
def config():
    """Manage silica configuration."""


@config.command(name="list")
def list_config():
    """List all configuration values."""
    config = load_config()

    table = Table(title="Silica Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")

    def add_config_rows(config, prefix=""):
        for key, value in sorted(config.items()):
            if isinstance(value, dict):
                add_config_rows(value, f"{prefix}{key}.")
            else:
                display_value = (
                    str(value) if value is not None else "[dim]Not set[/dim]"
                )
                table.add_row(f"{prefix}{key}", display_value)

    add_config_rows(config)
    console.print(table)


@config.command(name="get")
@click.argument("key")
def get_config(key):
    """Get a configuration value."""
    value = get_config_value(key)
    if value is None:
        console.print(f"[yellow]Configuration key '{key}' is not set.[/yellow]")
    else:
        if isinstance(value, dict):
            table = Table(title=f"Configuration for {key}")
            table.add_column("Key", style="cyan")
            table.add_column("Value", style="green")

            for k, v in sorted(value.items()):
                table.add_row(k, str(v) if v is not None else "[dim]Not set[/dim]")

            console.print(table)
        else:
            console.print(f"{key} = {value}")


@config.command(name="set")
@click.argument("key_value")
def set_config(key_value):
    """Set a configuration value (format: key=value)."""
    if "=" not in key_value:
        console.print("[red]Invalid format. Use key=value[/red]")
        return

    key, value = key_value.split("=", 1)

    # Convert string values to appropriate types
    if value.lower() == "true":
        value = True
    elif value.lower() == "false":
        value = False
    elif value.lower() == "none":
        value = None
    elif value.isdigit():
        value = int(value)

    set_config_value(key, value)
    console.print(f"[green]Set {key} = {value}[/green]")


@config.command(name="setup")
def setup():
    """Interactive setup wizard for silica configuration."""
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel
    from rich.layout import Layout
    import subprocess
    from silica.utils import check_piku_installed

    # Create a nice layout
    Layout()

    # Title panel
    title_panel = Panel(
        "[bold blue]Silica Setup Wizard[/bold blue]\n[italic]A tool for creating workspaces for agents on top of piku[/italic]",
        border_style="blue",
    )
    console.print(title_panel)
    console.print()

    console.print(
        "[bold]This wizard will guide you through setting up silica configuration.[/bold]"
    )
    console.print("[dim]Press Ctrl+C at any time to abort setup.[/dim]")
    console.print()

    # Check if piku is installed
    console.print("[bold]Checking piku installation...[/bold]")
    piku_installed = check_piku_installed()
    if piku_installed:
        console.print("✅ [green]Piku is installed and accessible[/green]")
    else:
        console.print("❌ [red]Piku doesn't seem to be installed or accessible[/red]")
        if Confirm.ask("Would you like to continue anyway?", default=True):
            console.print("[yellow]Continuing setup without piku verification[/yellow]")
        else:
            console.print(
                "[yellow]Setup aborted. Please install piku and try again.[/yellow]"
            )
            return

    console.print()
    console.print(
        Panel("[bold]Piku Connection Configuration[/bold]", border_style="cyan")
    )

    # Piku connection string
    piku_connection = Prompt.ask(
        "Piku connection string", default=get_config_value("piku_connection", "piku")
    )
    set_config_value("piku_connection", piku_connection)

    # Try to verify the piku installation
    try:
        verify_cmd = f"piku -r {piku_connection} version"
        result = subprocess.run(
            verify_cmd, capture_output=True, text=True, timeout=5, shell=True
        )
        if result.returncode == 0:
            console.print(
                f"✅ [green]Successfully connected to {piku_connection}[/green]"
            )
        else:
            console.print(
                f"❌ [yellow]Could not connect to {piku_connection}: {result.stderr.strip()}[/yellow]"
            )
            if Confirm.ask("Would you like to continue anyway?", default=True):
                console.print(
                    "[yellow]Continuing setup without verified connection[/yellow]"
                )
            else:
                console.print(
                    "[yellow]Setup aborted. Please configure SSH access to your piku server.[/yellow]"
                )
                return
    except Exception as e:
        console.print(f"❌ [yellow]Error verifying connection: {str(e)}[/yellow]")
        if Confirm.ask("Would you like to continue anyway?", default=True):
            console.print(
                "[yellow]Continuing setup without verified connection[/yellow]"
            )
        else:
            console.print(
                "[yellow]Setup aborted. Please configure SSH access to your piku server.[/yellow]"
            )
            return

    # Default workspace name
    workspace_name = Prompt.ask(
        "Default workspace name", default=get_config_value("workspace_name", "agent")
    )
    set_config_value("workspace_name", workspace_name)
    console.print()

    # API Keys section
    console.print(Panel("[bold]API Keys[/bold]", border_style="cyan"))
    console.print(
        "[dim]These keys are used to authenticate with various services.[/dim]"
    )
    console.print()

    # Check and configure various API keys
    api_keys = {
        "ANTHROPIC_API_KEY": "Anthropic API key",
        "GITHUB_TOKEN": "GitHub token",
        "BRAVE_SEARCH_API_KEY": "Brave Search API key",
    }

    for env_var, display_name in api_keys.items():
        configure_api_key(env_var, display_name)

    # Additional settings
    console.print()
    console.print(Panel("[bold]Additional Settings[/bold]", border_style="cyan"))

    # Ask if the user wants to set default project directory
    if Confirm.ask("Would you like to set a default project directory?", default=False):
        default_dir = Prompt.ask(
            "Default project directory",
            default=get_config_value(
                "default_project_dir", str(Path.home() / "projects")
            ),
        )
        set_config_value("default_project_dir", default_dir)

    # Final summary
    console.print()
    console.print(
        Panel("[bold green]Configuration Complete![/bold green]", border_style="green")
    )
    console.print()
    console.print("[bold]Your silica configuration:[/bold]")

    # Show a summary of the configuration
    config = load_config()

    table = Table(
        title="Silica Configuration", show_header=True, header_style="bold cyan"
    )
    table.add_column("Setting", style="dim")
    table.add_column("Value")

    def add_config_rows(config, prefix=""):
        for key, value in sorted(config.items()):
            if isinstance(value, dict):
                table.add_row(f"[bold]{prefix}{key}[/bold]", "")
                add_config_rows(value, f"  {prefix}")
            else:
                if key.lower().endswith(("key", "token", "password")):
                    display_value = "********" if value else "[dim]Not set[/dim]"
                else:
                    display_value = (
                        str(value) if value is not None else "[dim]Not set[/dim]"
                    )
                table.add_row(f"{prefix}{key}", display_value)

    add_config_rows(config)
    console.print(table)

    console.print()
    console.print("[green]You can change these settings anytime with:[/green]")
    console.print("  [bold]silica config:set key=value[/bold]")
    console.print("  [bold]silica config:setup[/bold] (to run this wizard again)")
    console.print()
    console.print(
        "✨ [bold green]You're all set! Try creating your first agent with:[/bold green]"
    )
    console.print("  [bold]silica create[/bold]")


def configure_api_key(env_var, display_name):
    """Helper function to configure any API key."""
    from rich.prompt import Prompt, Confirm

    config_key = f"api_keys.{env_var}"
    current_key = get_config_value(config_key, "")
    env_key = find_env_var(env_var)

    if env_key and not current_key:
        console.print(f"📝 [cyan]Found {display_name} in environment[/cyan]")
        if Confirm.ask(f"Would you like to use this {display_name}?", default=True):
            set_config_value(config_key, env_key)
            console.print(f"✅ [green]{display_name} set from environment[/green]")
            return

    if Confirm.ask(f"Do you want to set up {display_name}?", default=True):
        masked_key = "********" if current_key else ""

        api_key = Prompt.ask(f"{display_name}", password=True, default=masked_key)

        if api_key and api_key != "********":
            set_config_value(config_key, api_key)
            console.print(f"✅ [green]{display_name} updated[/green]")
        elif not api_key:
            set_config_value(config_key, None)
            console.print(f"[yellow]{display_name} cleared[/yellow]")


# Default command when running just 'silica config'
config.add_command(list_config, name="list")


# Make list_config the default command when just running 'silica config'
@config.command(name="")
@click.pass_context
def default_command(ctx):
    """Default command that runs 'list'."""
    ctx.forward(list_config)
