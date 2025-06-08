#!/usr/bin/env python3
"""
Agent HTTP Receiver for Silica Messaging

This lightweight HTTP server runs in agent workspaces to receive messages
from the root messaging app and forward them to the tmux session.
"""

import os
import subprocess
from flask import Flask, request, jsonify

app = Flask(__name__)

# Configuration
RECEIVER_PORT = int(os.environ.get("SILICA_RECEIVER_PORT", 8901))
WORKSPACE_NAME = os.environ.get("SILICA_WORKSPACE", "agent")
PROJECT_NAME = os.environ.get("SILICA_PROJECT", "unknown")
TMUX_SESSION = f"{WORKSPACE_NAME}-{PROJECT_NAME}"


def send_to_tmux(message: str, thread_id: str, sender: str, metadata: dict = None):
    """Send message to tmux session with proper context."""
    try:
        # Set thread context in tmux environment
        subprocess.run(
            ["tmux", "setenv", "-t", TMUX_SESSION, "SILICA_THREAD_ID", thread_id],
            check=True,
        )

        # Set sender context
        subprocess.run(
            ["tmux", "setenv", "-t", TMUX_SESSION, "SILICA_LAST_SENDER", sender],
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
                TMUX_SESSION,
                f"# Message: {message}",
                "Enter",
            ]
            subprocess.run(tmux_cmd, check=True)

        elif delivery_mode == "pane":
            # Send to dedicated message pane (create if needed)
            try:
                # Check if messages window exists
                subprocess.run(
                    [
                        "tmux",
                        "list-windows",
                        "-t",
                        TMUX_SESSION,
                        "-F",
                        "#{window_name}",
                    ],
                    capture_output=True,
                    check=True,
                )

                # Create messages window if it doesn't exist
                subprocess.run(
                    ["tmux", "new-window", "-t", TMUX_SESSION, "-n", "messages", "-d"],
                    check=False,
                )  # Don't fail if window already exists

                # Send message to messages window
                tmux_cmd = [
                    "tmux",
                    "send-keys",
                    "-t",
                    f"{TMUX_SESSION}:messages",
                    message,
                    "Enter",
                ]
                subprocess.run(tmux_cmd, check=True)

            except subprocess.CalledProcessError:
                # Fall back to status display
                delivery_mode = "status"

        if delivery_mode == "status":
            # Display in status bar (default, non-intrusive)
            display_msg = (
                f"New message from {sender}: {message[:50]}..."
                if len(message) > 50
                else f"New message from {sender}: {message}"
            )
            tmux_cmd = [
                "tmux",
                "display-message",
                "-t",
                TMUX_SESSION,
                "-d",
                "5000",
                display_msg,
            ]
            subprocess.run(tmux_cmd, check=True)

        return True

    except subprocess.CalledProcessError as e:
        print(f"Error sending to tmux: {e}")
        return False


@app.route("/health")
def health_check():
    """Health check endpoint."""
    return jsonify(
        {
            "status": "healthy",
            "workspace": WORKSPACE_NAME,
            "project": PROJECT_NAME,
            "tmux_session": TMUX_SESSION,
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
                {"status": "received", "thread_id": thread_id, "message_id": message_id}
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

        sessions = result.stdout.strip().split("\n") if result.stdout.strip() else []
        tmux_running = TMUX_SESSION in sessions

        # Get environment variables
        env_vars = {}
        if tmux_running:
            try:
                env_result = subprocess.run(
                    ["tmux", "showenv", "-t", TMUX_SESSION],
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
                "workspace": WORKSPACE_NAME,
                "project": PROJECT_NAME,
                "tmux_session": TMUX_SESSION,
                "tmux_running": tmux_running,
                "environment": env_vars,
                "receiver_port": RECEIVER_PORT,
            }
        )

    except Exception as e:
        return jsonify({"error": f"Failed to get status: {str(e)}"}), 500


if __name__ == "__main__":
    print(f"Starting Silica Agent Receiver for {WORKSPACE_NAME}-{PROJECT_NAME}")
    print(f"Listening on port {RECEIVER_PORT}")
    print(f"Target tmux session: {TMUX_SESSION}")

    app.run(host="0.0.0.0", port=RECEIVER_PORT, debug=False)
