"""Messaging commands for silica."""

import time
import subprocess
import webbrowser
from typing import Optional

import click
import requests
from rich.console import Console
from rich.table import Table

from silica.config import load_config
from silica.config.multi_workspace import load_project_config, get_default_workspace
from silica.utils.messaging import (
    check_messaging_app_exists,
    deploy_messaging_app,
    check_messaging_app_health,
    get_messaging_status,
    MESSAGING_APP_NAME,
)

console = Console()


def get_workspace_info(workspace_name: Optional[str] = None):
    """Get workspace and project information."""
    load_config()

    # If no workspace specified, use default
    if workspace_name is None:
        workspace_name = get_default_workspace()
        if workspace_name is None:
            console.print(
                "[red]No workspace specified and no default workspace set.[/red]"
            )
            console.print(
                "Use -w/--workspace to specify a workspace or set a default with 'silica workspace set-default'"
            )
            return None, None, None

    # Load project config to get workspace details
    project_config = load_project_config()
    if not project_config or "workspaces" not in project_config:
        console.print("[red]No workspace configuration found.[/red]")
        console.print("Run 'silica create' to create a workspace first.")
        return None, None, None

    workspace_config = project_config["workspaces"].get(workspace_name)
    if not workspace_config:
        console.print(f"[red]Workspace '{workspace_name}' not found.[/red]")
        console.print(
            f"Available workspaces: {', '.join(project_config['workspaces'].keys())}"
        )
        return None, None, None

    # Extract project name from app_name (format: workspace-project)
    app_name = workspace_config.get("app_name", "")
    if "-" in app_name:
        project_name = app_name.split("-", 1)[1]
    else:
        console.print(
            f"[red]Invalid app_name format in workspace config: {app_name}[/red]"
        )
        return None, None, None

    piku_connection = workspace_config.get("piku_connection", "piku")

    return workspace_name, project_name, piku_connection


def make_api_request(
    method: str,
    endpoint: str,
    data: Optional[dict] = None,
    params: Optional[dict] = None,
):
    """Make an API request to the messaging app."""
    try:
        url = f"http://localhost{endpoint}"
        headers = {"Host": MESSAGING_APP_NAME}

        if data:
            headers["Content-Type"] = "application/json"

        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=data,
            params=params,
            timeout=10,
        )

        if response.status_code >= 400:
            console.print(
                f"[red]API Error {response.status_code}: {response.text}[/red]"
            )
            return None

        return response.json()

    except requests.RequestException as e:
        console.print(f"[red]Failed to connect to messaging app: {e}[/red]")
        console.print("Make sure the messaging app is running with: silica msg status")
        return None


@click.group()
def msg():
    """Messaging system commands."""


@msg.command()
@click.option("-w", "--workspace", help="Workspace name")
def list(workspace):
    """List all threads for a workspace."""
    workspace_name, project_name, piku_connection = get_workspace_info(workspace)
    if not workspace_name:
        return

    # Get threads from API
    response = make_api_request(
        "GET", f"/api/v1/threads/{workspace_name}", params={"project": project_name}
    )

    if response is None:
        return

    threads = response.get("threads", [])

    if not threads:
        console.print(
            f"[yellow]No threads found for workspace {workspace_name}-{project_name}[/yellow]"
        )
        return

    # Display threads in a table
    table = Table(title=f"Threads for {workspace_name}-{project_name}")
    table.add_column("Thread ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Created", style="blue")
    table.add_column("Updated", style="blue")
    table.add_column("Status", style="yellow")

    for thread in threads:
        table.add_row(
            thread.get("thread_id", "")[:8] + "...",  # Shortened ID
            thread.get("title", ""),
            thread.get("created_at", "")[:19].replace("T", " "),
            thread.get("updated_at", "")[:19].replace("T", " "),
            thread.get("status", ""),
        )

    console.print(table)


@msg.command()
@click.argument("message")
@click.option("-w", "--workspace", help="Workspace name")
@click.option(
    "-t", "--thread", help="Thread ID (default: uses workspace default thread)"
)
def send(message, workspace, thread):
    """Send a message to a thread."""
    workspace_name, project_name, piku_connection = get_workspace_info(workspace)
    if not workspace_name:
        return

    # Use workspace name as default thread if none specified
    thread_id = thread or workspace_name

    # Send message via API
    response = make_api_request(
        "POST",
        "/api/v1/messages/send",
        data={
            "workspace": workspace_name,
            "project": project_name,
            "thread_id": thread_id,
            "message": message,
        },
    )

    if response:
        console.print(f"[green]Message sent successfully to thread {thread_id}[/green]")
    else:
        console.print("[red]Failed to send message[/red]")


@msg.command()
@click.argument("title")
@click.option("-w", "--workspace", help="Workspace name")
def new(title, workspace):
    """Create a new thread."""
    workspace_name, project_name, piku_connection = get_workspace_info(workspace)
    if not workspace_name:
        return

    # Create thread via API
    response = make_api_request(
        "POST",
        "/api/v1/threads/create",
        data={"workspace": workspace_name, "project": project_name, "title": title},
    )

    if response:
        thread_id = response.get("thread_id", "")
        console.print(f"[green]Created new thread: {title}[/green]")
        console.print(f"Thread ID: [cyan]{thread_id}[/cyan]")
    else:
        console.print("[red]Failed to create thread[/red]")


@msg.command()
@click.option("-w", "--workspace", help="Workspace name")
@click.option(
    "-t", "--thread", help="Thread ID (default: uses workspace default thread)"
)
@click.option("--tail", type=int, default=20, help="Number of recent messages to show")
def history(workspace, thread, tail):
    """View thread message history."""
    workspace_name, project_name, piku_connection = get_workspace_info(workspace)
    if not workspace_name:
        return

    # Use workspace name as default thread if none specified
    thread_id = thread or workspace_name

    # Get messages via API
    response = make_api_request(
        "GET",
        f"/api/v1/messages/{workspace_name}/{thread_id}",
        params={"project": project_name},
    )

    if response is None:
        return

    messages = response.get("messages", [])

    if not messages:
        console.print(f"[yellow]No messages found in thread {thread_id}[/yellow]")
        return

    # Show last N messages
    recent_messages = messages[-tail:] if len(messages) > tail else messages

    console.print(
        f"[bold]Thread: {thread_id} (showing last {len(recent_messages)} messages)[/bold]\n"
    )

    for msg in recent_messages:
        sender = msg.get("sender", "unknown")
        timestamp = msg.get("timestamp", "")[:19].replace("T", " ")
        content = msg.get("message", "")

        # Color code by sender
        sender_style = "green" if sender == "human" else "blue"

        console.print(
            f"[{sender_style}]{sender}[/{sender_style}] [dim]{timestamp}[/dim]"
        )
        console.print(f"  {content}\n")


@msg.command()
@click.option("-w", "--workspace", help="Workspace name")
@click.option(
    "-t", "--thread", help="Thread ID (default: uses workspace default thread)"
)
def follow(workspace, thread):
    """Follow messages in a thread in real-time."""
    workspace_name, project_name, piku_connection = get_workspace_info(workspace)
    if not workspace_name:
        return

    # Use workspace name as default thread if none specified
    thread_id = thread or workspace_name

    console.print(f"[green]Following thread {thread_id} (Ctrl+C to stop)[/green]\n")

    # Keep track of last message timestamp to avoid duplicates
    last_timestamp = None

    try:
        while True:
            # Get messages via API
            response = make_api_request(
                "GET",
                f"/api/v1/messages/{workspace_name}/{thread_id}",
                params={"project": project_name},
            )

            if response:
                messages = response.get("messages", [])

                # Filter to new messages
                new_messages = []
                for msg in messages:
                    msg_timestamp = msg.get("timestamp")
                    if last_timestamp is None or msg_timestamp > last_timestamp:
                        new_messages.append(msg)
                        last_timestamp = msg_timestamp

                # Display new messages
                for msg in new_messages:
                    sender = msg.get("sender", "unknown")
                    timestamp = msg.get("timestamp", "")[:19].replace("T", " ")
                    content = msg.get("message", "")

                    sender_style = "green" if sender == "human" else "blue"
                    console.print(
                        f"[{sender_style}]{sender}[/{sender_style}] [dim]{timestamp}[/dim]"
                    )
                    console.print(f"  {content}\n")

            time.sleep(2)  # Poll every 2 seconds

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped following thread[/yellow]")


@msg.command()
@click.option(
    "--force", is_flag=True, help="Force redeploy even if messaging app exists"
)
def deploy(force):
    """Deploy the root messaging app."""
    config = load_config()
    piku_connection = config.get("piku_connection", "piku")

    console.print("Deploying root messaging app...")
    success, message = deploy_messaging_app(piku_connection, force=force)

    if success:
        console.print(f"[green]{message}[/green]")
    else:
        console.print(f"[red]{message}[/red]")


@msg.command()
def undeploy():
    """Remove the messaging app."""
    config = load_config()
    piku_connection = config.get("piku_connection", "piku")

    if not check_messaging_app_exists(piku_connection):
        console.print("[yellow]Messaging app does not exist[/yellow]")
        return

    if click.confirm(
        "Are you sure you want to remove the messaging app? This will delete all threads and messages."
    ):
        try:
            subprocess.run(
                ["piku", "app", "destroy", piku_connection, MESSAGING_APP_NAME],
                check=True,
            )
            console.print("[green]Messaging app removed successfully[/green]")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Failed to remove messaging app: {e}[/red]")


@msg.command()
def status():
    """Check messaging system status."""
    config = load_config()
    piku_connection = config.get("piku_connection", "piku")

    console.print("[bold]Messaging System Status[/bold]\n")

    # Get overall status
    status = get_messaging_status(piku_connection)

    # Root messaging app status
    if status["messaging_app_exists"]:
        if status["messaging_app_healthy"]:
            console.print("[green]✓ Root messaging app: Running and healthy[/green]")
        else:
            console.print("[red]✗ Root messaging app: Exists but unhealthy[/red]")
    else:
        console.print("[red]✗ Root messaging app: Not deployed[/red]")
        console.print("  Run 'silica msg deploy' to deploy it")

    # Workspace status
    if status["workspaces"]:
        console.print("\n[bold]Active Workspaces:[/bold]")
        table = Table()
        table.add_column("Workspace", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Active Threads", style="yellow")

        for ws in status["workspaces"]:
            status_icon = "✓" if ws.get("connected", False) else "✗"
            table.add_row(
                ws.get("name", ""), status_icon, str(ws.get("active_threads", 0))
            )

        console.print(table)
    else:
        console.print("\n[yellow]No active workspaces found[/yellow]")


@msg.command()
@click.option("--no-open", is_flag=True, help="Don't automatically open browser")
def web(no_open):
    """Open the web interface."""
    if not check_messaging_app_health():
        console.print("[red]Messaging app is not running or unhealthy[/red]")
        console.print("Check status with: silica msg status")
        return

    url = "http://localhost"
    console.print(f"Web interface available at: [cyan]{url}[/cyan]")
    console.print(
        "(Make sure to set Host header to 'silica-messaging' if accessing directly)"
    )

    if not no_open:
        try:
            webbrowser.open("http://localhost")
            console.print("[green]Opened web interface in browser[/green]")
        except Exception as e:
            console.print(f"[yellow]Could not open browser: {e}[/yellow]")
            console.print(f"Please open {url} manually")
