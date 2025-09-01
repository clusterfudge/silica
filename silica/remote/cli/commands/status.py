"""Status command for silica."""

import subprocess
import cyclopts
from typing import Annotated, Optional
from rich.console import Console
from rich.table import Table
from pathlib import Path
from typing import List, Dict, Any

from silica.remote.config import get_silica_dir, find_git_root
from silica.remote.config.multi_workspace import list_workspaces
from silica.remote.utils.piku import (
    get_piku_connection,
    get_app_name,
    run_piku_in_silica,
)
# Agent configuration removed - hardcoded silica developer

console = Console()


def get_workspace_status(workspace_name: str, git_root: Path) -> Dict[str, Any]:
    """Get status information for a single workspace.

    Args:
        workspace_name: Name of the workspace to check
        git_root: Git root path

    Returns:
        Dictionary with status information
    """
    status = {
        "workspace": workspace_name,
        "piku_connection": get_piku_connection(git_root, workspace_name=workspace_name),
        "app_name": get_app_name(git_root, workspace_name=workspace_name),
        "process_status": [],
        "tmux_status": [],
        "agent_sessions": [],
        "error": None,
    }

    try:
        # Check if the app is running
        result = run_piku_in_silica(
            "ps", workspace_name=workspace_name, capture_output=True
        )
        status["process_status"] = result.stdout.strip().split("\n")

        # Check for agent tmux session
        try:
            # Using a simple command with known working format
            tmux_cmd = "tmux list-sessions -F '#{session_name} #{windows} #{created} #{?session_attached,attached,detached}' 2>/dev/null || echo 'No sessions found'"
            tmux_result = run_piku_in_silica(
                tmux_cmd,
                use_shell_pipe=True,
                workspace_name=workspace_name,
                capture_output=True,
                check=False,
            )

            tmux_output = tmux_result.stdout.strip()

            if "No sessions found" in tmux_output or not tmux_output:
                status["tmux_status"] = []
            else:
                lines = tmux_output.strip().split("\n")
                tmux_sessions = []

                for line in lines:
                    parts = line.strip().split()

                    if len(parts) >= 1:  # Check if there's at least a session name
                        session_name = parts[0]

                        # Check if the session name matches or contains the app name
                        if (
                            session_name == status["app_name"]
                            or status["app_name"] in session_name
                        ):
                            windows = parts[1] if len(parts) > 1 else "?"
                            created = parts[2] if len(parts) > 2 else "?"
                            status_text = parts[3] if len(parts) > 3 else "unknown"

                            tmux_sessions.append(
                                {
                                    "name": session_name,
                                    "windows": windows,
                                    "created": created,
                                    "status": status_text,
                                }
                            )

                status["tmux_status"] = tmux_sessions

        except subprocess.CalledProcessError as e:
            status["tmux_status"] = []
            status["error"] = f"Error checking tmux sessions: {e}"

        # Try to get agent sessions
        try:
            # Get agent type to use correct sessions command
            pass

            result = run_piku_in_silica(
                "silica developer sessions",
                use_shell_pipe=True,
                workspace_name=workspace_name,
                capture_output=True,
                check=False,
            )
            sessions_output = result.stdout.strip()

            if "No sessions found" in sessions_output:
                status["agent_sessions"] = []
            else:
                lines = sessions_output.split("\n")
                sessions = []

                # Skip the header line if there are multiple lines
                if len(lines) > 1:
                    for line in lines[1:]:  # Skip header
                        parts = line.split()
                        if len(parts) >= 3:
                            session_id = parts[0]
                            started = parts[1]
                            workdir = " ".join(parts[2:])
                            sessions.append(
                                {
                                    "id": session_id,
                                    "started": started,
                                    "workdir": workdir,
                                }
                            )

                status["agent_sessions"] = sessions

        except subprocess.CalledProcessError:
            status["agent_sessions"] = []

    except subprocess.CalledProcessError as e:
        error_output = e.stdout if e.stdout else str(e)
        status["error"] = f"Error: {error_output}"

    return status


def print_single_workspace_status(status: Dict[str, Any], detailed: bool = False):
    """Print status information for a single workspace.

    Args:
        status: Status dictionary for a workspace
        detailed: Whether to show detailed information
    """
    console.print(
        f"[bold]Status for workspace '[cyan]{status['workspace']}[/cyan]'[/bold]"
    )
    console.print(
        f"[dim]App name: {status['app_name']}, Connection: {status['piku_connection']}[/dim]"
    )

    # Add agent configuration information
    # Built-in silica developer - no configuration needed
    console.print("[bold]Agent:[/bold] [cyan]Built-in Silica Developer[/cyan]")

    if detailed:
        console.print(
            "[green]Command: uv run silica developer --dwr --persona autonomous_engineer[/green]"
        )

    # Print process status
    console.print("[green]Application status:[/green]")
    if not status["process_status"]:
        console.print("  [yellow]No processes found[/yellow]")
    else:
        for line in status["process_status"]:
            console.print(f"  {line}")

    # Print tmux session status
    console.print("\n[bold]Agent Session Status:[/bold]")
    if not status["tmux_status"]:
        console.print("[yellow]  Agent session is not running[/yellow]")
        console.print(
            f"[cyan]  Start the agent session with: [bold]si agent -w {status['workspace']}[/bold][/cyan]"
        )
    else:
        # Create a table for the agent sessions
        tmux_table = Table()
        tmux_table.add_column("Session", style="cyan")
        tmux_table.add_column("Windows", style="green")
        tmux_table.add_column("Created", style="blue")
        tmux_table.add_column("Status", style="yellow")

        for session in status["tmux_status"]:
            # Format status with color
            formatted_status = (
                "[green]attached[/green]"
                if session["status"] == "attached"
                else "[yellow]detached[/yellow]"
            )

            tmux_table.add_row(
                f"[bold cyan]{session['name']}[/bold cyan]",
                session["windows"],
                session["created"],
                formatted_status,
            )

        console.print(tmux_table)
        console.print(
            f"[cyan]To connect to the agent session, run: [bold]si agent -w {status['workspace']}[/bold][/cyan]"
        )

    # Print agent sessions
    console.print("\n[bold]Known Agent Sessions:[/bold]")
    if not status["agent_sessions"]:
        console.print("[yellow]  No agent sessions found[/yellow]")
    else:
        table = Table()
        table.add_column("ID", style="cyan")
        table.add_column("Started", style="green")
        table.add_column("Working Directory", style="blue")

        for session in status["agent_sessions"]:
            table.add_row(session["id"], session["started"], session["workdir"])

        console.print(table)

    if status["error"]:
        console.print(f"\n[red]{status['error']}[/red]")


def print_all_workspaces_summary(statuses: List[Dict[str, Any]]):
    """Print a summary of all workspaces.

    Args:
        statuses: List of status dictionaries for all workspaces
    """
    console.print("[bold]Status Summary for All Workspaces[/bold]")

    table = Table(title="Workspace Status")
    table.add_column("Workspace", style="cyan")
    table.add_column("Agent Type", style="magenta")
    table.add_column("App Name", style="blue")
    table.add_column("Processes", style="green")
    table.add_column("Agent Session", style="yellow")
    table.add_column("Status", style="red")

    for status in statuses:
        # Get agent type for this workspace
        pass

        agent_type = "silica_developer"  # only one agent type

        # Determine status indicators
        process_count = len(
            [p for p in status["process_status"] if p.strip() and "COMMAND" not in p]
        )
        process_status = (
            f"[green]{process_count} running[/green]"
            if process_count > 0
            else "[yellow]None[/yellow]"
        )

        tmux_status = "[yellow]Not running[/yellow]"
        if status["tmux_status"]:
            attached = any(s["status"] == "attached" for s in status["tmux_status"])
            tmux_status = (
                "[green]Attached[/green]" if attached else "[blue]Detached[/blue]"
            )

        str(len(status["agent_sessions"])) if status["agent_sessions"] else "0"

        overall_status = "[green]OK[/green]"
        if status["error"]:
            overall_status = "[red]Error[/red]"
        elif not process_count:
            overall_status = "[yellow]Inactive[/yellow]"

        table.add_row(
            status["workspace"],
            agent_type,
            status["app_name"],
            process_status,
            tmux_status,
            overall_status,
        )

    console.print(table)
    console.print(
        "\n[cyan]For detailed status, run: [bold]si status -w <workspace>[/bold][/cyan]"
    )


def status(
    workspace: Annotated[
        Optional[str],
        cyclopts.Parameter(
            name=["--workspace", "-w"],
            help="Specific workspace to check (default: show all workspaces)",
        ),
    ] = None,
    show_all: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--all", "-a"], help="Show detailed status for all workspaces"
        ),
    ] = False,
):
    """Fetch and visualize agent status across workspaces.

    If a specific workspace is provided with -w, shows detailed status for that workspace.
    Otherwise, shows a summary of all workspaces.
    """
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

    # Get all workspaces if no specific workspace is provided
    if workspace is None and not show_all:
        # Get a list of all workspaces
        workspaces_info = list_workspaces(silica_dir)
        if not workspaces_info:
            console.print("[yellow]No workspaces configured yet.[/yellow]")
            console.print(
                "Run [bold]silica create -w <workspace-name>[/bold] to create a workspace."
            )
            return

        # Get status for all workspaces
        all_statuses = []
        for workspace_info in workspaces_info:
            workspace_name = workspace_info["name"]
            status = get_workspace_status(workspace_name, git_root)
            all_statuses.append(status)

        # Print summary of all workspaces
        print_all_workspaces_summary(all_statuses)

    elif workspace is None and show_all:
        # Show detailed status for all workspaces
        workspaces_info = list_workspaces(silica_dir)
        if not workspaces_info:
            console.print("[yellow]No workspaces configured yet.[/yellow]")
            console.print(
                "Run [bold]silica create -w <workspace-name>[/bold] to create a workspace."
            )
            return

        for i, workspace_info in enumerate(workspaces_info):
            workspace_name = workspace_info["name"]
            status = get_workspace_status(workspace_name, git_root)

            # Add a separator between workspaces
            if i > 0:
                console.print("\n" + "=" * 80 + "\n")

            print_single_workspace_status(status, detailed=True)

    else:
        # Show detailed status for a specific workspace
        status = get_workspace_status(workspace, git_root)
        print_single_workspace_status(status, detailed=True)
