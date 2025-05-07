"""Agent command for silica."""

import click
from rich.console import Console

from silica.config import find_git_root
from silica.utils import piku as piku_utils
from silica.utils.piku import run_piku_in_silica

console = Console()


@click.command()
@click.option(
    "-w",
    "--workspace",
    help="Name for the workspace (default: agent)",
    default="agent",
)
def agent(workspace):
    """Connect to the agent tmux session.

    This command connects to the tmux session running the agent.
    If the session doesn't exist, it will be created.
    """
    try:
        # Get git root for app name
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        app_name = piku_utils.get_app_name(git_root)

        # Start an interactive shell and connect to the tmux session
        console.print(
            f"[green]Connecting to agent tmux session: [bold]{app_name}[/bold][/green]"
        )

        # Escape the tmux command properly
        run_piku_in_silica(
            f"tmux new-session -A -s {app_name} './AGENT.sh; exec bash'",
            workspace_name=workspace,
        )

    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
