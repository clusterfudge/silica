"""Agent command for silica."""

import click
import sys
from rich.console import Console

from silica.utils.piku_direct import agent_session, get_remote_info

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
        # Get server and app name from the workspace
        _, app_name = get_remote_info(workspace)

        # Start an interactive shell and connect to the tmux session
        console.print(
            f"[green]Connecting to agent tmux session: [bold]{app_name}[/bold][/green]"
        )

        # Use the direct implementation
        # This will replace the current process, so any code after this won't execute
        exit_code = agent_session(workspace_name=workspace)
        sys.exit(exit_code)

    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
