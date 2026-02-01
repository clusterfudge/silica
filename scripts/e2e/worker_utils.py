"""Utilities for spawning and managing workers in E2E tests."""

import json
import os
import subprocess
import base64


def create_worker_invite(
    deaddrop,
    namespace_id: str,
    namespace_secret: str,
    coordinator_id: str,
    coordinator_secret: str,
    room_id: str,
    worker_name: str,
) -> tuple[dict, str]:
    """Create a worker identity and invite URL.

    Returns:
        Tuple of (worker_identity, invite_url)
    """
    # Create worker identity
    worker = deaddrop.create_identity(
        ns=namespace_id,
        display_name=worker_name,
        ns_secret=namespace_secret,
    )

    # Add worker to room
    deaddrop.add_room_member(
        ns=namespace_id,
        room_id=room_id,
        identity_id=worker["id"],
        secret=coordinator_secret,
    )

    # Create invite URL (data: format)
    invite_data = {
        "namespace_id": namespace_id,
        "namespace_secret": namespace_secret,
        "identity_id": worker["id"],
        "identity_secret": worker["secret"],
        "room_id": room_id,
        "coordinator_id": coordinator_id,
    }
    invite_json = json.dumps(invite_data)
    invite_encoded = base64.b64encode(invite_json.encode()).decode()
    invite_url = f"data:application/json;base64,{invite_encoded}"

    return worker, invite_url


def spawn_worker_in_tmux(
    session_name: str, invite_url: str, agent_id: str, deaddrop_url: str
) -> bool:
    """Spawn a worker process in tmux.

    Args:
        session_name: Name for the tmux session
        invite_url: Invite URL for the worker
        agent_id: Agent ID for the worker
        deaddrop_url: URL of the deaddrop server

    Returns:
        True if spawn succeeded
    """
    script_dir = os.path.dirname(__file__)
    spawn_script = os.path.join(script_dir, "spawn_worker.sh")

    # Pass DEADDROP_URL through environment
    env = os.environ.copy()
    env["DEADDROP_URL"] = deaddrop_url

    result = subprocess.run(
        [spawn_script, session_name, invite_url, agent_id],
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        print(f"ERROR spawning worker: {result.stderr}")
        return False

    return True


def kill_tmux_session(session_name: str):
    """Kill a tmux session."""
    subprocess.run(
        ["tmux", "kill-session", "-t", session_name],
        capture_output=True,
    )
