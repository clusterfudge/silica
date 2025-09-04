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
from silica.remote.utils.antennae_client import get_antennae_client
from silica.remote.config.multi_workspace import is_local_workspace_for_cleanup
# Agent configuration removed - hardcoded silica developer

console = Console()


def get_workspace_status(
    workspace_name: str, git_root: Path, silica_dir: Path
) -> Dict[str, Any]:
    """Get status information for a workspace via HTTP API.

    Args:
        workspace_name: Name of the workspace to check
        git_root: Git root path
        silica_dir: .silica directory path

    Returns:
        Dictionary with status information
    """
    status = {
        "workspace": workspace_name,
        "accessible": False,
        "status_info": None,
        "connection_info": None,
        "error": None,
    }

    try:
        # Check if workspace is local (for cleanup purposes - we still use HTTP)
        is_local = is_local_workspace_for_cleanup(silica_dir, workspace_name)

        # Get HTTP client for this workspace
        client = get_antennae_client(silica_dir, workspace_name)

        # Try to get status via HTTP
        success, response = client.get_status()

        if success:
            status["accessible"] = True
            status["status_info"] = response
        else:
            status["error"] = response.get("error", "Failed to get status")

        # Also try to get connection info
        conn_success, conn_response = client.get_connection_info()
        if conn_success:
            status["connection_info"] = conn_response

        # Mark as local if needed
        status["is_local"] = is_local

    except Exception as e:
        status["error"] = f"Unexpected error: {str(e)}"

    return status


def get_workspace_status_legacy(workspace_name: str, git_root: Path) -> Dict[str, Any]:
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
    workspace_name = status["workspace"]
    console.print(f"[bold]Status for workspace '[cyan]{workspace_name}[/cyan]'[/bold]")

    # Check if workspace is accessible
    if not status["accessible"]:
        console.print("[red]❌ Antennae webapp is not accessible[/red]")
        if status["error"]:
            console.print(f"[red]Error: {status['error']}[/red]")

        # Show help for starting the workspace
        if status.get("is_local", False):
            console.print(
                f"[cyan]Start local workspace with: [bold]silica remote antennae --workspace {workspace_name}[/bold][/cyan]"
            )
        else:
            console.print(
                "[yellow]Remote workspace may be stopped or unreachable[/yellow]"
            )
        return

    console.print("[green]✅ Antennae webapp is accessible[/green]")

    # Get status info from HTTP response
    status_info = status.get("status_info", {})
    connection_info = status.get("connection_info", {})

    if status_info:
        console.print(
            f"[dim]Code directory: {status_info.get('code_directory', 'Unknown')}[/dim]"
        )

        # Built-in silica developer - no configuration needed
        console.print("[bold]Agent:[/bold] [cyan]Built-in Silica Developer[/cyan]")

        if detailed:
            agent_command = status_info.get(
                "agent_command",
                "uv run silica developer --dwr --persona autonomous_engineer",
            )
            console.print(f"[green]Command: {agent_command}[/green]")

        # Print repository status
        repo_info = status_info.get("repository", {})
        if repo_info:
            console.print("\n[bold]Repository:[/bold]")
            if repo_info.get("exists", False):
                console.print("  [green]✅ Repository exists[/green]")
                if repo_info.get("url"):
                    console.print(f"  [dim]URL: {repo_info['url']}[/dim]")
                if repo_info.get("branch"):
                    console.print(f"  [dim]Branch: {repo_info['branch']}[/dim]")
            else:
                console.print("  [yellow]⚠ No repository found[/yellow]")

        # Print tmux session status
        tmux_info = status_info.get("tmux_session", {})
        console.print("\n[bold]Agent Session Status:[/bold]")
        if tmux_info.get("running", False):
            session_info = tmux_info.get("info", {})
            session_name = (
                session_info.get("session_name", "unknown")
                if session_info
                else "unknown"
            )
            console.print(f"  [green]✅ Session '{session_name}' is running[/green]")
            if connection_info:
                console.print(
                    f"  [dim]Working directory: {connection_info.get('working_directory', 'Unknown')}[/dim]"
                )
        else:
            console.print("  [yellow]⚠ Agent session is not running[/yellow]")

        console.print(
            f"[cyan]To connect to the agent session, run: [bold]silica remote agent -w {workspace_name}[/bold][/cyan]"
        )

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
    table.add_column("Type", style="magenta")
    table.add_column("Accessible", style="green")
    table.add_column("Repository", style="blue")
    table.add_column("Agent Session", style="yellow")
    table.add_column("Status", style="red")

    for status in statuses:
        workspace_name = status["workspace"]

        # Determine workspace type
        workspace_type = "Local" if status.get("is_local", False) else "Remote"

        # Check accessibility
        accessible = "[green]✅[/green]" if status["accessible"] else "[red]❌[/red]"

        # Check repository status
        repo_status = "[yellow]Unknown[/yellow]"
        session_status = "[yellow]Unknown[/yellow]"

        if status["accessible"] and status["status_info"]:
            status_info = status["status_info"]
            repo_info = status_info.get("repository", {})
            tmux_info = status_info.get("tmux_session", {})

            if repo_info.get("exists", False):
                repo_status = "[green]✅[/green]"
            else:
                repo_status = "[yellow]⚠[/yellow]"

            if tmux_info.get("running", False):
                session_status = "[green]Running[/green]"
            else:
                session_status = "[yellow]Stopped[/yellow]"

        # Overall status
        overall_status = "[green]OK[/green]"
        if status["error"]:
            overall_status = "[red]Error[/red]"
        elif not status["accessible"]:
            overall_status = "[yellow]Offline[/yellow]"

        table.add_row(
            workspace_name,
            workspace_type,
            accessible,
            repo_status,
            session_status,
            overall_status,
        )

    console.print(table)
    console.print(
        "\n[cyan]For detailed status, run: [bold]silica remote status -w <workspace>[/bold][/cyan]"
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
            status = get_workspace_status(workspace_name, git_root, silica_dir)
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
            status = get_workspace_status(workspace_name, git_root, silica_dir)

            # Add a separator between workspaces
            if i > 0:
                console.print("\n" + "=" * 80 + "\n")

            print_single_workspace_status(status, detailed=True)

    else:
        # Show detailed status for a specific workspace
        status = get_workspace_status(workspace, git_root, silica_dir)
        print_single_workspace_status(status, detailed=True)
