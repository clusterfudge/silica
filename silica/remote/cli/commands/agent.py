"""Agent command for silica."""

import cyclopts
from typing import Annotated
from rich.console import Console

from silica.remote.config import find_git_root, get_silica_dir
from silica.remote.utils.antennae_client import get_antennae_client
from silica.remote.config.multi_workspace import is_local_workspace_for_cleanup

console = Console()


def agent(
    workspace: Annotated[
        str,
        cyclopts.Parameter(name=["--workspace", "-w"], help="Name for the workspace"),
    ] = "agent",
):
    """Connect to the agent tmux session.

    This command gets connection information from the antennae webapp and connects
    to the tmux session running the agent. For local workspaces, it connects directly.
    For remote workspaces, it uses the appropriate connection method.
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

        # Get HTTP client for this workspace
        client = get_antennae_client(silica_dir, workspace)

        # Get connection information
        console.print(
            f"[green]Getting connection info for workspace '[bold]{workspace}[/bold]'[/green]"
        )

        success, response = client.get_connection_info()

        if not success:
            error_msg = response.get("error", "Unknown error")
            console.print(f"[red]Error getting connection info: {error_msg}[/red]")

            # Provide helpful suggestions
            if "Connection failed" in error_msg or "Timeout" in error_msg:
                if is_local_workspace_for_cleanup(silica_dir, workspace):
                    console.print(
                        "[yellow]Workspace appears to be local. Start it with:[/yellow]"
                    )
                    console.print(
                        f"[bold]silica remote antennae --workspace {workspace}[/bold]"
                    )
                else:
                    console.print(
                        "[yellow]Remote workspace may be stopped or unreachable[/yellow]"
                    )
            return

        # Extract connection details
        session_name = response.get("session_name", workspace)
        tmux_running = response.get("tmux_running", False)
        working_directory = response.get("working_directory", ".")
        code_directory = response.get("code_directory", ".")

        if not tmux_running:
            console.print(
                f"[yellow]Tmux session '{session_name}' is not running[/yellow]"
            )
            console.print(
                "[yellow]Initialize the workspace to start the agent session[/yellow]"
            )
            return

        console.print(
            f"[green]Connecting to tmux session: [bold]{session_name}[/bold][/green]"
        )
        console.print(f"[dim]Working directory: {working_directory}[/dim]")
        console.print(f"[dim]Code directory: {code_directory}[/dim]")

        # Check if this is a local workspace
        if is_local_workspace_for_cleanup(silica_dir, workspace):
            # For local workspaces, connect directly to tmux
            console.print("[dim]Connecting to local tmux session...[/dim]")
            import subprocess

            subprocess.run(
                [
                    "tmux",
                    "new-session",
                    "-A",
                    "-s",
                    session_name,
                    "-c",
                    working_directory,
                ]
            )
        else:
            # For remote workspaces, use piku shell to connect
            console.print("[dim]Connecting to remote tmux session via piku...[/dim]")
            from silica.remote.utils.piku import run_piku_in_silica

            # Create or attach to the tmux session in the remote environment
            tmux_cmd = f"tmux new-session -A -s {session_name} -c {code_directory}"
            run_piku_in_silica(tmux_cmd, workspace_name=workspace)

    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
