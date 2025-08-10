"""Messaging commands for silica."""

import time
import subprocess
import webbrowser
from typing import Optional
import threading
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.error import URLError

import cyclopts
from typing import Annotated
import requests
from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown

from silica.remote.config import load_config
from silica.remote.config.multi_workspace import (
    load_project_config,
    get_default_workspace,
)
from silica.remote.utils.messaging import (
    check_messaging_app_exists,
    deploy_messaging_app,
    check_messaging_app_health,
    get_messaging_status,
    MESSAGING_APP_NAME,
)

console = Console()


def get_piku_connection() -> str:
    """Get the piku connection from config."""
    config = load_config()
    return config.get("piku_connection", "piku")


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
    piku_connection: Optional[str] = None,
):
    """Make an API request to the messaging app."""
    try:
        # Get base URL from piku connection
        if piku_connection is None:
            config = load_config()
            piku_connection = config.get("piku_connection", "piku")

        from silica.utils.messaging import _get_messaging_app_base_url

        base_url = _get_messaging_app_base_url(piku_connection)
        url = f"{base_url}{endpoint}"
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


msg = cyclopts.App(name="msg", help="Messaging system commands.")


@msg.command
def list():
    """List all global threads."""
    # Get threads from API
    piku_connection = get_piku_connection()
    response = make_api_request(
        "GET", "/api/v1/threads", piku_connection=piku_connection
    )

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


@msg.command
def send(
    message: str,
    thread: Annotated[
        Optional[str],
        cyclopts.Parameter(
            name=["--thread", "-t"],
            help="Thread ID (creates implicitly if doesn't exist)",
        ),
    ] = None,
    sender: Annotated[
        Optional[str],
        cyclopts.Parameter(
            name=["--sender", "-s"], help="Sender identity (default: auto-detected)"
        ),
    ] = None,
    title: Annotated[
        Optional[str], cyclopts.Parameter(help="Title for new threads")
    ] = None,
):
    """Send a message to a thread (creates thread implicitly if needed)."""
    if not thread:
        console.print("[red]Thread ID is required. Use -t/--thread to specify.[/red]")
        return

    # Use default sender if not specified
    if not sender:
        sender = get_default_sender()

    # Send message via API (will create thread implicitly)
    piku_connection = get_piku_connection()
    response = make_api_request(
        "POST",
        "/api/v1/messages/send",
        data={
            "thread_id": thread,
            "message": message,
            "sender": sender,
            "title": title,
        },
        piku_connection=piku_connection,
    )

    if response:
        delivery_statuses = response.get("delivery_statuses", [])
        console.print(f"[green]Message sent successfully to thread {thread}[/green]")
        if delivery_statuses:
            console.print(f"Delivery status: {', '.join(delivery_statuses)}")
    else:
        console.print("[red]Failed to send message[/red]")


@msg.command
def add_participant(thread_id: str, participant: str):
    """Add a participant to an existing thread."""
    piku_connection = get_piku_connection()
    response = make_api_request(
        "POST",
        f"/api/v1/threads/{thread_id}/participants",
        data={"participant": participant},
        piku_connection=piku_connection,
    )

    if response:
        console.print(f"[green]Added {participant} to thread {thread_id}[/green]")
    else:
        console.print("[red]Failed to add participant to thread[/red]")


@msg.command
def participants(thread_id: str):
    """List participants in a thread."""
    piku_connection = get_piku_connection()
    response = make_api_request(
        "GET",
        f"/api/v1/threads/{thread_id}/participants",
        piku_connection=piku_connection,
    )

    if response is None:
        return

    participants = response.get("participants", [])

    if not participants:
        console.print(f"[yellow]No participants found in thread {thread_id}[/yellow]")
        return

    console.print(f"[bold]Participants in thread {thread_id}:[/bold]")
    for participant in participants:
        console.print(f"  - {participant}")


@msg.command
def history(
    thread_id: str,
    tail: Annotated[
        int, cyclopts.Parameter(help="Number of recent messages to show")
    ] = 20,
):
    """View thread message history."""
    # Get messages via API
    piku_connection = get_piku_connection()
    response = make_api_request(
        "GET", f"/api/v1/threads/{thread_id}/messages", piku_connection=piku_connection
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

        # Render message as markdown if it contains markdown patterns
        if any(pattern in content for pattern in ["**", "*", "`", "#", "[", "```"]):
            console.print(Markdown(content))
        else:
            console.print(f"  {content}")
        console.print()


@msg.command
def follow(thread_id: str):
    """Follow messages in a thread in real-time."""
    console.print(f"[green]Following thread {thread_id} (Ctrl+C to stop)[/green]\n")

    # Keep track of last message timestamp to avoid duplicates
    last_timestamp = None
    piku_connection = get_piku_connection()

    try:
        while True:
            # Get messages via API
            response = make_api_request(
                "GET",
                f"/api/v1/threads/{thread_id}/messages",
                piku_connection=piku_connection,
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


@msg.command
def deploy(
    force: Annotated[
        bool, cyclopts.Parameter(help="Force redeploy even if messaging app exists")
    ] = False,
):
    """Deploy the root messaging app."""
    piku_connection = get_piku_connection()

    console.print("Deploying root messaging app...")
    success, message = deploy_messaging_app(piku_connection, force=force)

    if success:
        console.print(f"[green]{message}[/green]")
    else:
        console.print(f"[red]{message}[/red]")


@msg.command
def undeploy():
    """Remove the messaging app."""
    piku_connection = get_piku_connection()

    if not check_messaging_app_exists(piku_connection):
        console.print("[yellow]Messaging app does not exist[/yellow]")
        return

    from rich.prompt import Confirm

    if Confirm.ask(
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


@msg.command
def status():
    """Check messaging system status."""
    piku_connection = get_piku_connection()

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


class MessagingProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler that proxies requests to the remote messaging app."""

    def __init__(self, remote_base_url, *args, **kwargs):
        self.remote_base_url = remote_base_url
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self._proxy_request()

    def do_POST(self):
        self._proxy_request()

    def do_PUT(self):
        self._proxy_request()

    def do_DELETE(self):
        self._proxy_request()

    def _proxy_request(self):
        """Forward the request to the remote messaging app with proper headers."""
        try:
            # Construct the remote URL
            remote_url = f"{self.remote_base_url}{self.path}"

            # Read request body if present
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            # Create request with proper headers
            req = Request(remote_url, data=body, method=self.command)

            # Add the critical Host header for piku routing
            req.add_header("Host", MESSAGING_APP_NAME)

            # Forward other relevant headers (except Host)
            for header, value in self.headers.items():
                if header.lower() not in ["host", "connection", "content-length"]:
                    req.add_header(header, value)

            # Make the request to remote server
            response = urlopen(req, timeout=10)

            # Send response back to client
            self.send_response(response.getcode())

            # Forward response headers
            for header, value in response.headers.items():
                if header.lower() not in ["connection", "transfer-encoding"]:
                    self.send_header(header, value)
            self.end_headers()

            # Forward response body
            self.wfile.write(response.read())

        except URLError as e:
            # Handle connection errors to remote server
            self.send_error(
                502, f"Bad Gateway: Could not connect to messaging app - {e}"
            )
        except Exception as e:
            # Handle other errors
            self.send_error(500, f"Internal Server Error: {e}")

    def log_message(self, format, *args):
        """Suppress default logging to avoid cluttering console."""


def find_available_port(start_port=8080, max_attempts=10):
    """Find an available port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("localhost", port))
                return port
        except OSError:
            continue
    return None


def start_messaging_proxy(remote_base_url, local_port=None):
    """Start a local proxy server for the messaging app.

    Returns:
        tuple: (server, port) or (None, None) if failed to start
    """
    if local_port is None:
        local_port = find_available_port()

    if local_port is None:
        return None, None

    try:
        # Create handler class with remote URL
        def handler_class(*args, **kwargs):
            return MessagingProxyHandler(remote_base_url, *args, **kwargs)

        # Start server
        server = HTTPServer(("localhost", local_port), handler_class)

        # Start server in a separate thread
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        return server, local_port

    except Exception as e:
        console.print(f"[red]Failed to start proxy server: {e}[/red]")
        return None, None


@msg.command
def web(
    no_open: Annotated[
        bool, cyclopts.Parameter(help="Don't automatically open browser")
    ] = False,
    port: Annotated[
        Optional[int],
        cyclopts.Parameter(help="Local proxy port (default: auto-detect)"),
    ] = None,
):
    """Open the web interface via local proxy."""
    piku_connection = get_piku_connection()

    if not check_messaging_app_health(piku_connection):
        console.print("[red]Messaging app is not running or unhealthy[/red]")
        console.print("Check status with: silica msg status")
        return

    # Get remote messaging app URL
    from silica.utils.messaging import _get_messaging_app_base_url

    remote_base_url = _get_messaging_app_base_url(piku_connection)

    console.print(f"Starting local proxy for messaging app at {remote_base_url}")

    # Start proxy server
    server, proxy_port = start_messaging_proxy(remote_base_url, port)

    if server is None:
        console.print("[red]Failed to start local proxy server[/red]")
        console.print(
            f"You can try accessing the remote interface directly at: {remote_base_url}"
        )
        console.print("(Note: You may need to configure Host headers manually)")
        return

    proxy_url = f"http://localhost:{proxy_port}"
    console.print(f"[green]Proxy server started on {proxy_url}[/green]")
    console.print(
        "The proxy forwards requests to the remote messaging app with proper headers"
    )

    if not no_open:
        try:
            webbrowser.open(proxy_url)
            console.print("[green]Opened web interface in browser[/green]")
        except Exception as e:
            console.print(f"[yellow]Could not open browser: {e}[/yellow]")
            console.print(f"Please open {proxy_url} manually")

    console.print(f"\n[cyan]Web interface is available at: {proxy_url}[/cyan]")
    console.print("[yellow]Press Ctrl+C to stop the proxy server[/yellow]")

    try:
        # Keep the main thread alive until user interrupts
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down proxy server...[/yellow]")
        server.shutdown()
        console.print("[green]Proxy server stopped[/green]")
