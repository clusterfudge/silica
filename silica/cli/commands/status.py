"""Status command for silica."""

import subprocess
import click
from rich.console import Console
from rich.table import Table

from silica.config import get_silica_dir, find_git_root
from silica.utils.piku import (
    get_piku_connection,
    get_workspace_name,
    get_app_name,
    run_piku_in_silica,
)

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
        result = run_piku_in_silica("ps", workspace_name=workspace, capture_output=True)

        console.print("[green]Application status:[/green]")
        for line in result.stdout.strip().split("\n"):
            console.print(f"  {line}")

        # Check for agent tmux session
        console.print("\n[bold]Agent Session Status:[/bold]")
        try:
            # Check only the specific agent session
            # Using use_shell_pipe=True since we're running a shell command
            # Get all tmux sessions and filter in Python
            # Using a simple command with known working format
            # Output format will be: "session_name windows created attached/detached"
            tmux_cmd = "tmux list-sessions -F '#{session_name} #{windows} #{created} #{?session_attached,attached,detached}' 2>/dev/null || echo 'No sessions found'"
            tmux_result = run_piku_in_silica(
                tmux_cmd,
                use_shell_pipe=True,
                workspace_name=workspace,
                capture_output=True,
                check=False,
            )

            tmux_output = tmux_result.stdout.strip()

            # Debug output
            console.print("[dim]DEBUG - Raw tmux output:[/dim]")
            console.print(f"[dim]{tmux_output}[/dim]")
            console.print(f"[dim]DEBUG - Looking for app_name: '{app_name}'[/dim]")

            if "No sessions found" in tmux_output or not tmux_output:
                console.print("[yellow]  Agent session is not running[/yellow]")
                console.print(
                    "[cyan]  Start the agent session with: [bold]si agent[/bold][/cyan]"
                )
            else:
                # Create a table for the agent sessions
                tmux_table = Table()
                tmux_table.add_column("Session", style="cyan")
                tmux_table.add_column("Windows", style="green")
                tmux_table.add_column("Created", style="blue")
                tmux_table.add_column("Status", style="yellow")

                # Parse each line of the tmux output
                lines = tmux_output.strip().split("\n")
                agent_session_found = False

                console.print(f"[dim]DEBUG - Found {len(lines)} sessions[/dim]")

                for line in lines:
                    # Debug output for each line
                    console.print(f"[dim]DEBUG - Processing line: '{line}'[/dim]")

                    parts = line.strip().split()

                    if len(parts) >= 1:  # Check if there's at least a session name
                        session_name = parts[0]
                        console.print(
                            f"[dim]DEBUG - Session name: '{session_name}', comparing with app_name: '{app_name}'[/dim]"
                        )

                        # Check if the session name matches or contains the app name
                        # This is more flexible in case the session naming has variations
                        if session_name == app_name or app_name in session_name:
                            agent_session_found = True
                            console.print(
                                f"[dim]DEBUG - MATCH FOUND - Session name '{session_name}' matches or contains app_name '{app_name}'[/dim]"
                            )

                            # Handle cases where we might not have all parts
                            windows = parts[1] if len(parts) > 1 else "?"
                            created = parts[2] if len(parts) > 2 else "?"
                            status = parts[3] if len(parts) > 3 else "unknown"

                            # Format status with color
                            formatted_status = (
                                "[green]attached[/green]"
                                if status == "attached"
                                else "[yellow]detached[/yellow]"
                            )

                            tmux_table.add_row(
                                f"[bold cyan]{session_name}[/bold cyan]",
                                windows,
                                created,
                                formatted_status,
                            )
                    else:
                        console.print(
                            "[dim]DEBUG - Skipping line: insufficient parts[/dim]"
                        )

                if agent_session_found:
                    console.print(tmux_table)
                    console.print(
                        "[cyan]To connect to the agent session, run: [bold]si agent[/bold][/cyan]"
                    )
                else:
                    console.print(
                        f"[dim]DEBUG - No session matched app_name: '{app_name}'[/dim]"
                    )
                    console.print("[yellow]  Agent session is not running[/yellow]")
                    console.print(
                        "[cyan]  Start the agent session with: [bold]si agent[/bold][/cyan]"
                    )

        except subprocess.CalledProcessError as e:
            console.print(f"[yellow]  Error checking agent session: {e}[/yellow]")

    except subprocess.CalledProcessError as e:
        console.print(
            f"[red]Error: {e.output.strip() if hasattr(e, 'output') else str(e)}[/red]"
        )
