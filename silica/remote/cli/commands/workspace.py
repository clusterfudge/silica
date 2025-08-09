"""Workspace management commands for silica."""

import cyclopts
from rich.console import Console
from rich.table import Table

from silica.remote.config import find_git_root, get_silica_dir
from silica.remote.config.multi_workspace import (
    list_workspaces,
    get_default_workspace,
    set_default_workspace,
)

console = Console()


workspace = cyclopts.App(name="workspace", help="Manage silica workspaces.")


@workspace.command
def list():
    """List all configured workspaces."""
    # Find git root
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    # Get the silica directory
    silica_dir = get_silica_dir(git_root)
    if not silica_dir or not (silica_dir / "config.yaml").exists():
        console.print(
            "[red]Error: No silica environment found in this repository.[/red]"
        )
        console.print("Run 'silica create' first to set up the environment.")
        return

    # Get all workspaces
    workspaces = list_workspaces(silica_dir)

    if not workspaces:
        console.print("[yellow]No workspaces configured yet.[/yellow]")
        console.print("Run 'silica create -w <workspace-name>' to create a workspace.")
        return

    # Display workspaces in a table
    table = Table(title="Configured Workspaces")
    table.add_column("Name", style="cyan")
    table.add_column("Default", style="green")
    table.add_column("App Name", style="blue")
    table.add_column("Connection", style="magenta")
    table.add_column("Branch", style="yellow")

    for workspace in workspaces:
        config = workspace["config"]
        table.add_row(
            workspace["name"],
            "✓" if workspace["is_default"] else "",
            config.get("app_name", f"{workspace['name']}-{git_root.name}"),
            config.get("piku_connection", "piku"),
            config.get("branch", "main"),
        )

    console.print(table)


@workspace.command
def set_default(name: str):
    """Set the default workspace."""
    # Find git root
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    # Get the silica directory
    silica_dir = get_silica_dir(git_root)
    if not silica_dir or not (silica_dir / "config.yaml").exists():
        console.print(
            "[red]Error: No silica environment found in this repository.[/red]"
        )
        console.print("Run 'silica create' first to set up the environment.")
        return

    # Get all workspaces
    workspaces = list_workspaces(silica_dir)

    # Check if the workspace exists
    workspace_exists = any(ws["name"] == name for ws in workspaces)
    if not workspace_exists:
        console.print(f"[red]Error: Workspace '{name}' does not exist.[/red]")
        console.print("Run 'silica workspace list' to see available workspaces.")
        return

    # Set the default workspace
    set_default_workspace(silica_dir, name)
    console.print(f"[green]Default workspace set to '{name}'.[/green]")


@workspace.command
def get_default():
    """Get the current default workspace."""
    # Find git root
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    # Get the silica directory
    silica_dir = get_silica_dir(git_root)
    if not silica_dir or not (silica_dir / "config.yaml").exists():
        console.print(
            "[red]Error: No silica environment found in this repository.[/red]"
        )
        console.print("Run 'silica create' first to set up the environment.")
        return

    # Get the default workspace
    default_workspace = get_default_workspace(silica_dir)
    console.print(f"Current default workspace: [cyan]{default_workspace}[/cyan]")
