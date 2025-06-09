"""Messaging commands for silica."""

import time
import subprocess
import webbrowser
from typing import Optional

import click
import requests
from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown

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


def get_default_sender() -> str:
    """Get default sender (human or current workspace participant)."""
    try:
        # Try to get workspace info for agent context
        workspace_name = get_default_workspace()
        if workspace_name:
            project_config = load_project_config()
            if project_config and "workspaces" in project_config:
                workspace_config = project_config["workspaces"].get(workspace_name)
                if workspace_config:
                    app_name = workspace_config.get("app_name", "")
                    if "-" in app_name:
                        return app_name  # Return workspace-project format
    except Exception:
        pass

    return "human"  # Default fallback


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
def list():
    """List all global threads."""
    # Get threads from API
    response = make_api_request("GET", "/api/v1/threads")

    if response is None:
        return

    threads = response.get("threads", [])

    if not threads:
        console.print("[yellow]No threads found[/yellow]")
        return

    # Display threads in a table
    table = Table(title="Global Threads")
    table.add_column("Thread ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Participants", style="yellow")
    table.add_column("Created", style="blue")
    table.add_column("Updated", style="blue")

    for thread in threads:
        participants = ", ".join(thread.get("participants", []))
        table.add_row(
            thread.get("thread_id", ""),
            thread.get("title", ""),
            participants[:30] + "..." if len(participants) > 30 else participants,
            thread.get("created_at", "")[:19].replace("T", " "),
            thread.get("updated_at", "")[:19].replace("T", " "),
        )

    console.print(table)


@msg.command()
@click.argument("message")
@click.option("-t", "--thread", help="Thread ID (creates implicitly if doesn't exist)")
@click.option("-s", "--sender", help="Sender identity (default: auto-detected)")
@click.option("--title", help="Title for new threads")
def send(message, thread, sender, title):
    """Send a message to a thread (creates thread implicitly if needed)."""
    if not thread:
        console.print("[red]Thread ID is required. Use -t/--thread to specify.[/red]")
        return

    # Use default sender if not specified
    if not sender:
        sender = get_default_sender()

    # Send message via API (will create thread implicitly)
    response = make_api_request(
        "POST",
        "/api/v1/messages/send",
        data={
            "thread_id": thread,
            "message": message,
            "sender": sender,
            "title": title,
        },
    )

    if response:
        delivery_statuses = response.get("delivery_statuses", [])
        console.print(f"[green]Message sent successfully to thread {thread}[/green]")
        if delivery_statuses:
            console.print(f"Delivery status: {', '.join(delivery_statuses)}")
    else:
        console.print("[red]Failed to send message[/red]")


@msg.command()
@click.argument("thread_id")
@click.argument("participant")
def add_participant(thread_id, participant):
    """Add a participant to an existing thread."""
    response = make_api_request(
        "POST",
        f"/api/v1/threads/{thread_id}/participants",
        data={"participant": participant},
    )

    if response:
        console.print(f"[green]Added {participant} to thread {thread_id}[/green]")
    else:
        console.print("[red]Failed to add participant to thread[/red]")


@msg.command()
@click.argument("thread_id")
def participants(thread_id):
    """List participants in a thread."""
    response = make_api_request("GET", f"/api/v1/threads/{thread_id}/participants")

    if response is None:
        return

    participants = response.get("participants", [])

    if not participants:
        console.print(f"[yellow]No participants found in thread {thread_id}[/yellow]")
        return

    console.print(f"[bold]Participants in thread {thread_id}:[/bold]")
    for participant in participants:
        console.print(f"  - {participant}")


@msg.command()
@click.argument("thread_id")
@click.option("--tail", type=int, default=20, help="Number of recent messages to show")
def history(thread_id, tail):
    """View thread message history."""
    # Get messages via API
    response = make_api_request("GET", f"/api/v1/threads/{thread_id}/messages")

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

        # Render message as markdown if it contains markdown patterns
        if any(pattern in content for pattern in ["**", "*", "`", "#", "[", "```"]):
            console.print(Markdown(content))
        else:
            console.print(f"  {content}")
        console.print()


@msg.command()
@click.argument("thread_id")
def follow(thread_id):
    """Follow messages in a thread in real-time."""
    console.print(f"[green]Following thread {thread_id} (Ctrl+C to stop)[/green]\n")

    # Keep track of last message timestamp to avoid duplicates
    last_timestamp = None

    try:
        while True:
            # Get messages via API
            response = make_api_request("GET", f"/api/v1/threads/{thread_id}/messages")

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

                    # Render message as markdown if it contains markdown patterns
                    if any(
                        pattern in content
                        for pattern in ["**", "*", "`", "#", "[", "```"]
                    ):
                        console.print(Markdown(content))
                    else:
                        console.print(f"  {content}")
                    console.print()

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
    status_info = get_messaging_status(piku_connection)

    # Root messaging app status
    if status_info["messaging_app_exists"]:
        if status_info["messaging_app_healthy"]:
            console.print("[green]✓ Root messaging app: Running and healthy[/green]")
        else:
            console.print("[red]✗ Root messaging app: Exists but unhealthy[/red]")
    else:
        console.print("[red]✗ Root messaging app: Not deployed[/red]")
        console.print("  Run 'silica msg deploy' to deploy it")

    # Workspace status
    if status_info["workspaces"]:
        console.print("\n[bold]Active Workspaces:[/bold]")
        table = Table()
        table.add_column("Workspace", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Active Threads", style="yellow")

        for ws in status_info["workspaces"]:
            status_icon = "✓" if ws.get("connected", False) else "✗"
            table.add_row(
                ws.get("name", ""), status_icon, str(ws.get("active_threads", 0))
            )

        console.print(table)
    else:
        console.print("\n[yellow]No active workspaces found[/yellow]")


@msg.command()
@click.option("--no-open", is_flag=True, help="Don't automatically open browser")
@click.option("--port", type=int, help="Port to use (default: messaging app port)")
def web(no_open, port):
    """Open the web interface."""
    if not check_messaging_app_health():
        console.print("[red]Messaging app is not running or unhealthy[/red]")
        console.print("Check status with: silica msg status")
        return

    # Construct URL with port if specified
    if port:
        url = f"http://localhost:{port}"
    else:
        url = "http://localhost"

    console.print(f"Web interface available at: [cyan]{url}[/cyan]")
    console.print(
        "(Make sure to set Host header to 'silica-messaging' if accessing directly)"
    )

    if not no_open:
        try:
            webbrowser.open(url)
            console.print("[green]Opened web interface in browser[/green]")
        except Exception as e:
            console.print(f"[yellow]Could not open browser: {e}[/yellow]")
            console.print(f"Please open {url} manually")
