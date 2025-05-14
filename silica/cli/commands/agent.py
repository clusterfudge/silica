"""Agent command for silica."""

import click
from rich.console import Console

from silica.config import find_git_root
from silica.utils import piku as piku_utils
from silica.utils import piku_direct

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

        # Use the piku_direct module to run the command with headers suppressed
        # This will replace the current process, so code after this won't execute
        # in the success case
        piku_direct.run_piku(
            "tmux",
            args=["new-session", "-A", "-s", app_name, "./AGENT.sh; exec bash"],
            remote=workspace,
            suppress_headers=True,
            exec_mode=True,
        )

    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
