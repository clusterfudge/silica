"""Destroy command for silica."""

import subprocess
import shutil
import click
from rich.console import Console
from rich.prompt import Confirm

from silica.config import get_silica_dir, find_git_root
from silica.utils import piku as piku_utils
from silica.utils.piku import get_piku_connection, get_app_name

console = Console()


@click.command()
@click.option("--force", is_flag=True, help="Force destruction without confirmation")
@click.option(
    "-w",
    "--workspace",
    help="Name for the workspace (default: agent)",
    default="agent",
)
def destroy(force, workspace):
    """Destroy the agent environment."""
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    silica_dir = get_silica_dir()
    if not silica_dir or not (silica_dir / "config.yaml").exists():
        console.print(
            "[red]Error: No silica environment found in this repository.[/red]"
        )
        return

    # Use our utility functions to get workspace name, app name, etc.
    app_name = get_app_name(git_root)
    piku_connection = get_piku_connection(git_root)

    if not workspace or not piku_connection or not app_name:
        console.print("[red]Error: Invalid configuration.[/red]")
        return

    if not force and not Confirm.ask(f"Are you sure you want to destroy {app_name}?"):
        console.print("[yellow]Aborted.[/yellow]")
        return

    console.print(f"[bold]Destroying {app_name}...[/bold]")

    try:
        # Destroy the piku application using run_piku_in_silica
        force_flag = "--force" if force else ""
        piku_utils.run_piku_in_silica(f"destroy {force_flag}", workspace_name=workspace)

        # Remove local .silica directory contents
        if Confirm.ask(
            "Do you want to remove local silica environment files?", default=True
        ):
            # Just clean the contents but keep the directory
            for item in silica_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

            console.print("[green]Local silica environment files removed.[/green]")

        console.print(f"[green bold]Successfully destroyed {app_name}![/green bold]")

    except subprocess.CalledProcessError as e:
        error_output = e.stderr.decode() if e.stderr else str(e)
        console.print(f"[red]Error destroying environment: {error_output}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
