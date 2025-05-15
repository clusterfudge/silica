"""Tell command for silica."""

import click
from rich.console import Console

from silica.config import find_git_root
from silica.utils import piku as piku_utils

console = Console()


@click.command()
@click.argument("message", nargs=-1, required=True)
@click.option(
    "-w",
    "--workspace",
    help="Name for the workspace (default: agent)",
    default="agent",
)
def tell(message, workspace):
    """Send a message to the agent tmux session using send-keys.

    This command sends a message to the agent's tmux session using the tmux send-keys command.
    It's useful for programmatically sending instructions to the agent.
    """
    try:
        # Get git root for app name
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        app_name = piku_utils.get_app_name(git_root)

        # Combine the message parts into a single string
        message_text = " ".join(message)

        # Send the message to the tmux session
        console.print(
            f"[green]Sending message to agent tmux session: [bold]{app_name}[/bold][/green]"
        )

        # Use run_piku_in_silica to execute the command with the correct configuration
        # The command is to send keys to the tmux session
        # Use -- to properly separate local and remote flags to handle escaping
        # Use single quotes around the message to better preserve whitespace
        # Also echo the message to stderr so we can see exactly what's being sent
        command = f"run -- \"echo 'Sending: {message_text}' >&2 && tmux send-keys -t {app_name} '{message_text}' C-m\""

        # Run the command in the silica environment
        result = piku_utils.run_piku_in_silica(
            command, workspace_name=workspace, capture_output=True
        )
        if result.returncode == 0:
            console.print("[green]Message sent successfully.[/green]")
        else:
            console.print(
                f"[red]Error sending message: \n{result.stdout}\n{result.stderr}[/red]"
            )

    except Exception as e:
        console.print(f"[red]Error sending message: {e}[/red]")
