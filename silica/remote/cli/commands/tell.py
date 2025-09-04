"""Tell command for silica."""

import cyclopts
from typing import Annotated
from rich.console import Console

from silica.remote.config import find_git_root, get_silica_dir
from silica.remote.utils.antennae_client import get_antennae_client

console = Console()


def tell(
    *message: str,
    workspace: Annotated[
        str,
        cyclopts.Parameter(name=["--workspace", "-w"], help="Name for the workspace"),
    ] = "agent",
):
    """Send a message to the agent via the antennae webapp.

    This command sends a message to the agent running in the workspace's tmux session
    via the antennae webapp's /tell endpoint.
    """
    try:
        # Get git root and silica dir
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        silica_dir = get_silica_dir()
        if not silica_dir or not (silica_dir / "config.yaml").exists():
            console.print(
                "[red]Error: No silica environment found in this repository.[/red]"
            )
            console.print(
                "Run [bold]silica remote create[/bold] to set up a workspace first."
            )
            return

        # Combine the message parts into a single string
        message_text = " ".join(message)

        if not message_text.strip():
            console.print("[red]Error: No message provided.[/red]")
            return

        # Get HTTP client for this workspace
        client = get_antennae_client(silica_dir, workspace)

        # Send the message via HTTP
        console.print(
            f"[green]Sending message to workspace '[bold]{workspace}[/bold]'[/green]"
        )
        console.print(f"[dim]Message: {message_text}[/dim]")

        success, response = client.tell(message_text)

        if success:
            console.print("[green]Message sent successfully.[/green]")
        else:
            error_msg = response.get("error", "Unknown error")
            detail = response.get("detail", "")
            console.print(f"[red]Error sending message: {error_msg}[/red]")
            if detail:
                console.print(f"[red]Detail: {detail}[/red]")

    except Exception as e:
        console.print(f"[red]Error sending message: {e}[/red]")
