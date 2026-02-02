"""Utilities for spawning and managing workers in E2E tests."""

import os
import subprocess
from urllib.parse import urlencode, urlparse, urlunparse


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

    # Create real invite URL using deaddrop's invite system
    invite = deaddrop.create_invite(
        ns=namespace_id,
        identity_id=worker["id"],
        identity_secret=worker["secret"],
        ns_secret=namespace_secret,
        display_name=f"Worker: {worker_name}",
    )

    # Add coordination metadata as query parameters
    invite_url = invite["invite_url"]
    parsed = urlparse(invite_url)
    coord_params = urlencode(
        {
            "room": room_id,
            "coordinator": coordinator_id,
        }
    )
    new_query = f"{parsed.query}&{coord_params}" if parsed.query else coord_params
    invite_url = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )

    return worker, invite_url


def spawn_worker_in_tmux(session_name: str, invite_url: str, agent_id: str) -> bool:
    """Spawn a worker process in tmux.

    Args:
        session_name: Name for the tmux session
        invite_url: Invite URL for the worker (includes server domain)
        agent_id: Agent ID for the worker

    Returns:
        True if spawn succeeded
    """
    script_dir = os.path.dirname(__file__)

    result = subprocess.run(
        [
            os.path.join(script_dir, "spawn_worker.sh"),
            session_name,
            invite_url,
            agent_id,
        ],
        capture_output=True,
        text=True,
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
