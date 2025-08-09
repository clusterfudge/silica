"""Messaging system deployment and management utilities."""

import subprocess
import time
from pathlib import Path
from rich.console import Console
from typing import Dict, Tuple
import requests

from silica.remote.utils import piku as piku_utils

console = Console()

MESSAGING_APP_NAME = "silica-messaging"


def _get_messaging_app_base_url(piku_connection: str) -> str:
    """Extract the base URL for the messaging app from piku connection string.

    Args:
        piku_connection: Piku connection string (e.g., "piku", "piku@host", "piku@host.domain.com")

    Returns:
        Base URL for messaging app (e.g., "http://localhost", "http://host", "http://host.domain.com")
    """
    if "@" in piku_connection:
        # Extract hostname from "piku@host" format
        host = piku_connection.split("@", 1)[1]
        return f"http://{host}"
    else:
        # Local development case - use localhost
        return "http://localhost"


def check_messaging_app_exists(piku_connection: str) -> bool:
    """Check if the silica-messaging app exists on piku."""
    try:
        # Use piku app list to check if messaging app exists
        # For the messaging app, we use "piku" as the remote name
        result = subprocess.run(
            ["piku", "-r", "piku", "app", "list"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            # Check if our messaging app is in the list
            return MESSAGING_APP_NAME in result.stdout
        return False
    except subprocess.CalledProcessError:
        return False


def check_messaging_app_health(piku_connection: str, timeout: int = 30) -> bool:
    """Check if the messaging app is responding to health checks."""
    try:
        base_url = _get_messaging_app_base_url(piku_connection)
        response = requests.get(
            f"{base_url}/health", headers={"Host": MESSAGING_APP_NAME}, timeout=5
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def deploy_messaging_app(piku_connection: str, force: bool = False) -> Tuple[bool, str]:
    """
    Deploy the silica-messaging app to piku.

    Args:
        piku_connection: Piku connection string (e.g., "piku")
        force: Whether to force redeploy if app already exists

    Returns:
        Tuple of (success, message)
    """
    if not force and check_messaging_app_exists(piku_connection):
        if check_messaging_app_health(piku_connection):
            return True, "Messaging app already exists and is healthy"
        else:
            console.print(
                "[yellow]Messaging app exists but is unhealthy, redeploying...[/yellow]"
            )

    try:
        # Get the silica installation directory to access messaging app source
        silica_install_dir = Path(__file__).parent.parent
        messaging_dir = silica_install_dir / "messaging"

        if not messaging_dir.exists():
            return False, f"Messaging app source not found at {messaging_dir}"

        console.print(f"Deploying messaging app from {messaging_dir}...")

        # Create temporary directory for messaging app deployment
        import tempfile
        import shutil

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "messaging"

            # Copy messaging app files to temp directory
            shutil.copytree(messaging_dir, temp_path)

            # Initialize git repo in temp directory
            subprocess.run(["git", "init"], cwd=temp_path, check=True)
            subprocess.run(["git", "add", "."], cwd=temp_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial messaging app commit"],
                cwd=temp_path,
                check=True,
            )

            # Add piku remote
            remote_url = f"{piku_connection}:{MESSAGING_APP_NAME}"
            subprocess.run(
                ["git", "remote", "add", "piku", remote_url], cwd=temp_path, check=True
            )

            # Push to piku
            console.print(f"Pushing to piku remote: {remote_url}")
            subprocess.run(["git", "push", "piku", "main"], cwd=temp_path, check=True)

            # Set essential environment variables for the messaging app
            # Run this within the temp directory context where the piku remote is available
            console.print("Configuring messaging app environment...")

            # Set NGINX_SERVER_NAME for hostname routing (DATA_DIR not needed for piku)
            config_cmd = [
                "piku",
                "config:set",
                f"NGINX_SERVER_NAME={MESSAGING_APP_NAME}",
            ]
            subprocess.run(config_cmd, cwd=temp_path, check=True)

        # Wait for app to become healthy
        console.print("Waiting for messaging app to become healthy...")
        for i in range(30):  # Wait up to 30 seconds
            if check_messaging_app_health(piku_connection):
                console.print("[green]Messaging app is healthy and ready![/green]")
                return True, "Messaging app deployed successfully"
            time.sleep(1)

        return False, "Messaging app deployed but failed health check"

    except subprocess.CalledProcessError as e:
        return False, f"Failed to deploy messaging app: {e}"
    except Exception as e:
        return False, f"Unexpected error deploying messaging app: {e}"


def setup_workspace_messaging(
    workspace_name: str, project_name: str, piku_connection: str
) -> Tuple[bool, str]:
    """
    Set up messaging for a workspace.

    Args:
        workspace_name: Name of the workspace
        project_name: Name of the project (usually repository name)
        piku_connection: Piku connection string

    Returns:
        Tuple of (success, message)
    """
    try:
        app_name = f"{workspace_name}-{project_name}"

        # Set up environment variables in the workspace
        console.print(f"Setting up messaging environment for {app_name}...")

        env_vars = {
            "SILICA_WORKSPACE": workspace_name,
            "SILICA_PROJECT": project_name,
            "SILICA_PARTICIPANT": f"{workspace_name}-{project_name}",
            "SILICA_RECEIVER_PORT": "8901",
            "SILICA_MESSAGE_DELIVERY": "status",  # Default to status bar delivery
            "NGINX_SERVER_NAME": app_name,  # Enable hostname routing for workspace
        }

        # Set environment variables using piku
        # Use run_piku_in_silica to run config:set from the workspace git context
        config_args = [f"{k}={v}" for k, v in env_vars.items()]
        config_cmd = f"config:set {' '.join(config_args)}"

        piku_utils.run_piku_in_silica(config_cmd, workspace_name=workspace_name)

        # Create default thread for the workspace by sending an initial message
        console.print(f"Creating default thread for {app_name}...")

        # Wait a moment for the messaging app to be ready
        time.sleep(2)

        try:
            base_url = _get_messaging_app_base_url(piku_connection)
            response = requests.post(
                f"{base_url}/api/v1/messages/send",
                headers={
                    "Host": MESSAGING_APP_NAME,
                    "Content-Type": "application/json",
                },
                json={
                    "thread_id": workspace_name,  # Use workspace name as default thread ID
                    "message": f"Workspace {workspace_name} initialized",
                    "sender": f"{workspace_name}-{project_name}",
                    "title": "Default",
                },
                timeout=10,
            )

            if response.status_code in [200, 201]:
                console.print(
                    f"[green]Default thread created: {workspace_name}[/green]"
                )
            else:
                console.print(
                    f"[yellow]Warning: Failed to create default thread: {response.text}[/yellow]"
                )

        except requests.RequestException as e:
            console.print(
                f"[yellow]Warning: Failed to create default thread: {e}[/yellow]"
            )

        return True, "Workspace messaging setup completed"

    except subprocess.CalledProcessError as e:
        return False, f"Failed to setup workspace messaging: {e}"
    except Exception as e:
        return False, f"Unexpected error setting up workspace messaging: {e}"


def start_agent_receiver(workspace_name: str, piku_connection: str) -> Tuple[bool, str]:
    """
    Start the agent HTTP receiver as a background service using silica command.

    Args:
        workspace_name: Name of the workspace
        piku_connection: Piku connection string

    Returns:
        Tuple of (success, message)
    """
    try:
        console.print("Starting agent HTTP receiver...")

        # Start agent receiver using silica messaging receiver command
        receiver_cmd = """
# Start agent receiver as background service using silica command
if pgrep -f "silica messaging receiver" > /dev/null; then
    echo "Agent receiver already running"
else
    echo "Starting agent receiver..."
    nohup uv run silica messaging receiver > receiver.log 2>&1 &
    sleep 3
    if pgrep -f "silica messaging receiver" > /dev/null; then
        echo "Agent receiver started successfully"
    else
        echo "Failed to start agent receiver"
        exit 1
    fi
fi
"""

        piku_utils.run_piku_in_silica(
            receiver_cmd, workspace_name=workspace_name, use_shell_pipe=True, check=True
        )

        console.print("[green]Agent HTTP receiver started[/green]")
        return True, "Agent receiver started successfully"

    except subprocess.CalledProcessError as e:
        return False, f"Failed to start agent receiver: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"


def add_messaging_to_workspace_environment(
    workspace_name: str, piku_connection: str
) -> Tuple[bool, str]:
    """
    Add messaging function sourcing to workspace bashrc and auto-start receiver.

    Args:
        workspace_name: Name of the workspace
        piku_connection: Piku connection string

    Returns:
        Tuple of (success, message)
    """
    try:
        # Get the silica installation path in the remote environment
        console.print("Adding messaging functions to workspace environment...")

        # Create script to add messaging setup to bashrc
        messaging_setup = """
# Silica messaging support - added by workspace creation
export SILICA_INSTALL_DIR="$(uv run python -c 'import silica; print(silica.__file__.replace(\"/__init__.py\", \"\"))')"

# Source messaging function if available
if [[ -f "$SILICA_INSTALL_DIR/agent/messaging.sh" ]]; then
    source "$SILICA_INSTALL_DIR/agent/messaging.sh"
fi

# Note: Agent receiver is now started by Procfile (web: uv run silica messaging receiver --port $PORT)
# No need to auto-start here as piku will handle it
"""

        # Add to .bashrc in the workspace
        bashrc_cmd = f"""
if ! grep -q "Silica messaging support" ~/.bashrc; then
    echo '{messaging_setup}' >> ~/.bashrc
    echo 'Added messaging functions to .bashrc'
else
    echo 'Messaging functions already configured in .bashrc'
fi
"""

        piku_utils.run_piku_in_silica(
            bashrc_cmd, workspace_name=workspace_name, use_shell_pipe=True, check=True
        )

        console.print(
            "[green]Messaging functions added to workspace environment[/green]"
        )
        return True, "Messaging environment setup completed"

    except subprocess.CalledProcessError as e:
        return False, f"Failed to add messaging to workspace environment: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"


def get_messaging_status(piku_connection: str) -> Dict:
    """Get the status of the messaging system."""
    status = {
        "messaging_app_exists": False,
        "messaging_app_healthy": False,
        "workspaces": [],
    }

    # Check if messaging app exists
    status["messaging_app_exists"] = check_messaging_app_exists(piku_connection)

    if status["messaging_app_exists"]:
        # Check if messaging app is healthy
        status["messaging_app_healthy"] = check_messaging_app_health(piku_connection)

        # Get workspace status from messaging app if healthy
        if status["messaging_app_healthy"]:
            try:
                base_url = _get_messaging_app_base_url(piku_connection)
                response = requests.get(
                    f"{base_url}/api/v1/workspaces/status",
                    headers={"Host": MESSAGING_APP_NAME},
                    timeout=5,
                )
                if response.status_code == 200:
                    data = response.json()
                    status["workspaces"] = data.get("workspaces", [])
            except requests.RequestException:
                pass

    return status
