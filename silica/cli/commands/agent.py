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

        # Use 'piku shell' pipe to ensure login shell environment is loaded
        # Then create or attach to tmux session with environment variables preserved
        tmux_cmd = f"tmux new-session -A -s {app_name} './AGENT.sh; exec bash'"
        run_piku_in_silica(
            tmux_cmd,
            workspace_name=workspace,
            use_shell_pipe=True,  # Use shell pipe to ensure env vars are loaded
        )

    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
