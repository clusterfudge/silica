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

    # Gather ALL confirmations upfront before taking any destructive actions
    confirmations = {}

    # Check if there's a tmux session for this app
    has_tmux_session = False
    try:
        check_cmd = f"tmux has-session -t {app_name} 2>/dev/null || echo 'no_session'"
        check_result = piku_utils.run_piku_in_silica(
            check_cmd,
            workspace_name=workspace,
            use_shell_pipe=True,
            capture_output=True,
        )
        has_tmux_session = "no_session" not in check_result.stdout
    except Exception:
        has_tmux_session = False  # Assume no session on error

    # Main confirmation for app destruction
    if force:
        confirmations["destroy_app"] = True
    else:
        confirmation_message = f"Are you sure you want to destroy {app_name}?"
        if has_tmux_session:
            confirmation_message += (
                f"\nThis will also terminate the tmux session for {app_name}."
            )

        confirmations["destroy_app"] = Confirm.ask(confirmation_message)

    if not confirmations["destroy_app"]:
        console.print("[yellow]Aborted.[/yellow]")
        return

    # Confirmation for local file removal - only ask if we're proceeding with destruction
    if confirmations["destroy_app"]:
        confirmations["remove_local_files"] = Confirm.ask(
            "Do you want to remove local silica environment files?", default=True
        )

    # Now that we have all confirmations, proceed with destruction actions
    console.print(f"[bold]Destroying {app_name}...[/bold]")

    try:
        # First terminate tmux sessions if they exist and user confirmed
        if has_tmux_session and confirmations["destroy_app"]:
            console.print(f"[bold]Terminating tmux session for {app_name}...[/bold]")
            try:
                kill_cmd = f"tmux kill-session -t {app_name}"
                piku_utils.run_piku_in_silica(
                    kill_cmd, workspace_name=workspace, use_shell_pipe=True
                )
                console.print(f"[green]Terminated tmux session for {app_name}.[/green]")
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Could not terminate tmux session: {e}[/yellow]"
                )

        # Now destroy the piku application
        force_flag = "--force" if force else ""
        piku_utils.run_piku_in_silica(f"destroy {force_flag}", workspace_name=workspace)

        # Remove local .silica directory contents if confirmed
        if confirmations["remove_local_files"]:
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
