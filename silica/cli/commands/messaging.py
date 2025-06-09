"""Messaging system commands for silica."""

import os
import subprocess
from flask import Flask, request, jsonify

import click
from rich.console import Console

console = Console()


@click.group()
def messaging():
    """Messaging system commands."""


@messaging.command()
@click.option(
    "--port",
    type=int,
    default=None,
    help="Port to listen on (default: $SILICA_RECEIVER_PORT or 8901)",
)
@click.option("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
def receiver(port, host):
    """Start agent HTTP receiver for message delivery."""

    # Get configuration from environment
    workspace_name = os.environ.get("SILICA_WORKSPACE", "agent")
    project_name = os.environ.get("SILICA_PROJECT", "unknown")

    # Port priority: --port flag > $PORT env var > $SILICA_RECEIVER_PORT > default 8901
    receiver_port = port or int(
        os.environ.get("PORT", os.environ.get("SILICA_RECEIVER_PORT", 8901))
    )
    tmux_session = f"{workspace_name}-{project_name}"

    console.print(f"Starting Silica Agent Receiver for {workspace_name}-{project_name}")
    console.print(f"Listening on {host}:{receiver_port}")
    console.print(f"Target tmux session: {tmux_session}")

    # Create Flask app for receiver
    app = Flask(__name__)

    def send_to_tmux(message: str, thread_id: str, sender: str, metadata: dict = None):
        """Send message to tmux session with proper context."""
        try:
            # Set thread context in tmux environment
            subprocess.run(
                ["tmux", "setenv", "-t", tmux_session, "SILICA_THREAD_ID", thread_id],
                check=True,
            )

            # Set sender context
            subprocess.run(
                ["tmux", "setenv", "-t", tmux_session, "SILICA_LAST_SENDER", sender],
                check=True,
            )

            # Get message delivery preference
            delivery_mode = os.environ.get("SILICA_MESSAGE_DELIVERY", "status")

            if delivery_mode == "direct":
                # Send message directly to current pane
                tmux_cmd = [
                    "tmux",
                    "send-keys",
                    "-t",
                    tmux_session,
                    f"# Message from {sender}: {message}",
                    "Enter",
                ]
                subprocess.run(tmux_cmd, check=True)

            elif delivery_mode == "pane":
                # Send to dedicated message pane (create if needed)
                try:
                    # Create messages window if it doesn't exist
                    subprocess.run(
                        [
                            "tmux",
                            "new-window",
                            "-t",
                            tmux_session,
                            "-n",
                            "messages",
                            "-d",
                        ],
                        check=False,
                    )  # Don't fail if window already exists

                    # Send message to messages window
                    tmux_cmd = [
                        "tmux",
                        "send-keys",
                        "-t",
                        f"{tmux_session}:messages",
                        f"[{sender}] {message}",
                        "Enter",
                    ]
                    subprocess.run(tmux_cmd, check=True)

                except subprocess.CalledProcessError:
                    # Fall back to status display
                    delivery_mode = "status"

            if delivery_mode == "status":
                # Display in status bar (default, non-intrusive)
                display_msg = (
                    f"Message from {sender}: {message[:50]}..."
                    if len(message) > 50
                    else f"Message from {sender}: {message}"
                )
                tmux_cmd = [
                    "tmux",
                    "display-message",
                    "-t",
                    tmux_session,
                    "-d",
                    "5000",
                    display_msg,
                ]
                subprocess.run(tmux_cmd, check=True)

            return True

        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error sending to tmux: {e}[/red]")
            return False

    @app.route("/health")
    def health_check():
        """Health check endpoint."""
        return jsonify(
            {
                "status": "healthy",
                "workspace": workspace_name,
                "project": project_name,
                "tmux_session": tmux_session,
                "receiver_port": receiver_port,
            }
        )

    @app.route("/api/v1/agent/receive", methods=["POST"])
    def receive_message():
        """Receive message from root messaging app."""
        try:
            # Get thread ID from headers
            thread_id = request.headers.get("X-Thread-ID")
            message_id = request.headers.get("X-Message-ID")
            sender = request.headers.get("X-Sender", "unknown")

            if not thread_id:
                return jsonify({"error": "X-Thread-ID header required"}), 400

            # Get message data from request
            data = request.get_json()
            if not data:
                return jsonify({"error": "JSON payload required"}), 400

            message = data.get("message", "")
            metadata = data.get("metadata", {})

            if not message:
                return jsonify({"error": "message field required"}), 400

            # Forward to tmux session
            success = send_to_tmux(message, thread_id, sender, metadata)

            if success:
                return jsonify(
                    {
                        "status": "received",
                        "thread_id": thread_id,
                        "message_id": message_id,
                    }
                )
            else:
                return jsonify({"error": "Failed to forward message to tmux"}), 500

        except Exception as e:
            return jsonify({"error": f"Internal error: {str(e)}"}), 500

    @app.route("/api/v1/agent/status")
    def agent_status():
        """Get agent status information."""
        try:
            # Check if tmux session exists
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
                check=False,
            )

            sessions = (
                result.stdout.strip().split("\n") if result.stdout.strip() else []
            )
            tmux_running = tmux_session in sessions

            # Get environment variables
            env_vars = {}
            if tmux_running:
                try:
                    env_result = subprocess.run(
                        ["tmux", "showenv", "-t", tmux_session],
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    for line in env_result.stdout.split("\n"):
                        if line.startswith("SILICA_"):
                            if "=" in line:
                                key, value = line.split("=", 1)
                                env_vars[key] = value
                except subprocess.CalledProcessError:
                    pass

            return jsonify(
                {
                    "workspace": workspace_name,
                    "project": project_name,
                    "tmux_session": tmux_session,
                    "tmux_running": tmux_running,
                    "environment": env_vars,
                    "receiver_port": receiver_port,
                }
            )

        except Exception as e:
            return jsonify({"error": f"Failed to get status: {str(e)}"}), 500

    # Start the Flask app
    try:
        app.run(host=host, port=receiver_port, debug=False)
    except Exception as e:
        console.print(f"[red]Failed to start receiver: {e}[/red]")
        raise click.ClickException(f"Failed to start receiver: {e}")


@messaging.command()
@click.option(
    "--port",
    type=int,
    default=None,
    help="Port for messaging app (default: $PORT or 5000)",
)
def app(port):
    """Start the root messaging app (for development/testing)."""
    # Import the messaging app
    from silica.messaging.app import app as messaging_app

    app_port = port or int(os.environ.get("PORT", 5000))

    console.print(f"Starting Silica Root Messaging App on port {app_port}")
    console.print(
        "This is typically deployed via piku, but can be run locally for testing"
    )

    try:
        messaging_app.run(host="0.0.0.0", port=app_port, debug=True)
    except Exception as e:
        console.print(f"[red]Failed to start messaging app: {e}[/red]")
        raise click.ClickException(f"Failed to start messaging app: {e}")


if __name__ == "__main__":
    messaging()
