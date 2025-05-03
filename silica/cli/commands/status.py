"""Status command for silica."""

import subprocess
import click
from rich.console import Console
from rich.table import Table

from silica.config import get_silica_dir, find_git_root
from silica.utils.piku import get_piku_connection, get_workspace_name, get_app_name
from silica.utils import piku as piku_utils

console = Console()


@click.command()
def status():
    """Fetch and visualize agent status and conversations."""
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    silica_dir = get_silica_dir()
    if not silica_dir or not (silica_dir / "config.yaml").exists():
        console.print(
            "[red]Error: No silica environment found in this repository.[/red]"
        )
        console.print("Run [bold]silica create[/bold] to set up an environment first.")
        return

    # Use utility functions for connection, workspace, and app_name
    piku_connection = get_piku_connection(git_root)
    workspace = get_workspace_name(git_root)
    app_name = get_app_name(git_root)

    if not piku_connection or not workspace or not app_name:
        console.print("[red]Error: Invalid configuration.[/red]")
        return

    console.print(f"[bold]Status for workspace '{workspace}'[/bold]")
    console.print(f"[dim]App name: {app_name}, Connection: {piku_connection}[/dim]")

    try:
        # Check if the app is running using run_piku_in_silica
        result = piku_utils.run_piku_in_silica(
            f"status {app_name}", workspace_name=workspace, capture_output=True
        )

        console.print("[green]Application status:[/green]")
        for line in result.stdout.strip().split("\n"):
            console.print(f"  {line}")

        # Try to get sessions
        console.print("\n[bold]Active sessions:[/bold]")
        try:
            # Use run_piku_in_silica to run the hdev sessions command
            result = piku_utils.run_piku_in_silica(
                "hdev sessions",
                use_shell_pipe=True,
                workspace_name=workspace,
                capture_output=True,
            )
            sessions_output = result.stdout.strip()

            # Parse the output into a list of sessions
            lines = sessions_output.split("\n")

            # Skip if no sessions found
            if "No sessions found" in sessions_output:
                console.print("[yellow]  No sessions found[/yellow]")
            else:
                # Process the lines to extract session info
                table = Table()
                table.add_column("ID", style="cyan")
                table.add_column("Started", style="green")
                table.add_column("Working Directory", style="blue")

                # Skip the header line if there are multiple lines
                if len(lines) > 1:
                    for line in lines[1:]:  # Skip header
                        parts = line.split()
                        if len(parts) >= 3:
                            session_id = parts[0]
                            started = parts[1]
                            workdir = " ".join(parts[2:])
                            table.add_row(session_id, started, workdir)

                console.print(table)
        except subprocess.CalledProcessError:
            console.print(
                "[yellow]  Could not retrieve sessions (hdev may not be installed or configured)[/yellow]"
            )

    except subprocess.CalledProcessError as e:
        console.print(
            f"[red]Error: {e.output.strip() if hasattr(e, 'output') else str(e)}[/red]"
        )
