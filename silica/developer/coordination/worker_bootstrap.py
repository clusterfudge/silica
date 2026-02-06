"""Worker bootstrap - claim invite and connect to coordination namespace.

This module handles the startup flow for worker agents spawned by a coordinator.
Workers detect their coordination context via environment variables and connect
to the coordinator's deaddrop namespace.
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

from deadrop import Deaddrop

from .client import CoordinationContext

logger = logging.getLogger(__name__)


# Environment variable names
DEADDROP_INVITE_URL = "DEADDROP_INVITE_URL"
COORDINATION_AGENT_ID = "COORDINATION_AGENT_ID"


@dataclass
class WorkerBootstrapResult:
    """Result of bootstrapping a worker into a coordination session."""

    context: CoordinationContext
    agent_id: str
    display_name: str
    namespace_id: str
    room_id: str
    coordinator_id: str


def get_invite_from_env() -> Optional[str]:
    """Check if coordination invite URL is in environment."""
    return os.environ.get(DEADDROP_INVITE_URL)


def get_agent_id_from_env() -> Optional[str]:
    """Get agent ID from environment."""
    return os.environ.get(COORDINATION_AGENT_ID)


def is_coordinated_worker() -> bool:
    """Check if this agent should run as a coordinated worker."""
    return get_invite_from_env() is not None


def claim_invite_and_connect(
    invite_url: Optional[str] = None,
) -> WorkerBootstrapResult:
    """Claim a deaddrop invite and connect to the coordination namespace.

    The invite URL format is: https://server/join/{invite_id}#{key}?room=...&coordinator=...
    - Server domain is extracted from the URL itself
    - Encryption key is in the fragment
    - Coordination metadata (room, coordinator) is in query params

    Args:
        invite_url: Invite URL (defaults to DEADDROP_INVITE_URL env var)

    Returns:
        WorkerBootstrapResult with context and connection info

    Raises:
        RuntimeError: If invite URL not provided or invalid
        ConnectionError: If unable to connect to deaddrop server
    """
    invite_url = invite_url or get_invite_from_env()
    if not invite_url:
        raise RuntimeError(
            f"No invite URL provided. Set {DEADDROP_INVITE_URL} environment variable "
            "or pass invite_url parameter."
        )

    # Parse invite URL
    if not (invite_url.startswith("http://") or invite_url.startswith("https://")):
        raise RuntimeError(f"Invalid invite URL format: {invite_url[:50]}...")

    parsed = urlparse(invite_url)
    server_url = f"{parsed.scheme}://{parsed.netloc}"

    # Extract coordination metadata from query params
    query_params = parse_qs(parsed.query)
    room_id = query_params.get("room", [None])[0]
    coordinator_id = query_params.get("coordinator", [None])[0]

    # Connect and claim
    deaddrop = Deaddrop.remote(url=server_url)
    logger.info(f"Claiming invite from server: {server_url}...")

    try:
        claim_result = deaddrop.claim_invite(invite_url)
    except Exception as e:
        raise ConnectionError(f"Failed to claim invite: {e}") from e

    # Extract credentials
    identity_id = claim_result.get("identity_id")
    identity_secret = claim_result.get("secret")
    namespace_id = claim_result.get("ns")
    display_name = claim_result.get("display_name", "Worker")

    if not all([identity_id, identity_secret, namespace_id]):
        raise RuntimeError(
            f"Invalid claim result, missing required fields: {claim_result}"
        )

    # Create coordination context
    context = CoordinationContext(
        deaddrop=deaddrop,
        namespace_id=namespace_id,
        namespace_secret=None,  # Workers don't get namespace secret
        identity_id=identity_id,
        identity_secret=identity_secret,
        room_id=room_id,
        coordinator_id=coordinator_id,
    )

    agent_id = get_agent_id_from_env() or f"worker-{identity_id[:8]}"
    logger.info(f"Worker connected as {display_name} (ID: {agent_id})")

    return WorkerBootstrapResult(
        context=context,
        agent_id=agent_id,
        display_name=display_name,
        namespace_id=namespace_id,
        room_id=room_id,
        coordinator_id=coordinator_id,
    )


def setup_worker_tools(bootstrap_result: WorkerBootstrapResult) -> None:
    """Set up worker coordination tools with the bootstrap context."""
    from silica.developer.tools.worker_coordination import set_worker_context

    set_worker_context(
        context=bootstrap_result.context,
        agent_id=bootstrap_result.agent_id,
    )


def setup_worker_sandbox_permissions(
    sandbox,
    bootstrap_result: WorkerBootstrapResult,
    timeout: float = 300.0,
) -> None:
    """Configure sandbox to use coordination-based permissions."""
    from silica.developer.coordination.worker_permissions import (
        setup_worker_sandbox_permissions as _setup_permissions,
    )

    _setup_permissions(
        sandbox=sandbox,
        context=bootstrap_result.context,
        agent_id=bootstrap_result.agent_id,
        timeout=timeout,
    )


def bootstrap_worker(
    invite_url: Optional[str] = None,
) -> Optional[WorkerBootstrapResult]:
    """Full worker bootstrap - connect and set up tools."""
    if not invite_url and not is_coordinated_worker():
        return None

    result = claim_invite_and_connect(invite_url=invite_url)
    setup_worker_tools(result)
    return result


def get_worker_persona():
    """Get the worker persona for coordinated workers."""
    from pathlib import Path

    from silica.developer import personas
    from silica.developer.personas.worker_agent import PERSONA as WORKER_PERSONA
    from silica.developer.utils import wrap_text_as_content_block

    return personas.Persona(
        system_block=wrap_text_as_content_block(WORKER_PERSONA),
        base_directory=Path("~/.silica/personas/coordination_worker").expanduser(),
    )


def integrate_worker_startup(
    user_interface,
) -> Optional[WorkerBootstrapResult]:
    """Integrate worker coordination into agent startup."""
    if not is_coordinated_worker():
        return None

    user_interface.handle_system_message(
        "[bold cyan]🤝 Coordination Mode Detected[/bold cyan]\n"
        "Connecting to coordinator...",
        markdown=False,
    )

    try:
        result = bootstrap_worker()

        if result:
            from silica.developer.coordination import Idle

            idle_msg = Idle(agent_id=result.agent_id)
            result.context.send_to_coordinator(idle_msg)

            user_interface.handle_system_message(
                f"[green]✓ Connected as {result.display_name}[/green]\n"
                f"[dim]Agent ID: {result.agent_id}[/dim]\n"
                f"[dim]Namespace: {result.namespace_id}[/dim]\n"
                "[dim]Waiting for task assignment...[/dim]",
                markdown=False,
            )

        return result

    except Exception as e:
        user_interface.handle_system_message(
            f"[red]❌ Failed to connect to coordinator: {e}[/red]",
            markdown=False,
        )
        raise


def get_worker_initial_prompt(bootstrap_result: WorkerBootstrapResult) -> str:
    """Generate the initial prompt for a worker agent."""
    return f"""You are now connected to a coordination session as Worker Agent "{bootstrap_result.display_name}" (ID: {bootstrap_result.agent_id}).

**Your first action: Check your inbox for task assignments.**

Use `check_inbox()` to see if you have any pending tasks from the coordinator.

If you have a task:
1. Acknowledge it with `send_to_coordinator("ack", task_id=...)`
2. Execute the task using your available tools
3. Report progress periodically with `send_to_coordinator("progress", ...)`
4. When complete, send results with `send_to_coordinator("result", ...)`
5. Call `mark_idle()` when ready for the next task

If no task yet, call `mark_idle()` and wait. The coordinator will assign work when ready.

Begin by checking your inbox now."""


def create_worker_task_loop_prompt() -> str:
    """Create a prompt that reminds the worker to continue the task loop."""
    return """**Task Loop Reminder**

You've completed your current task. To continue working:

1. If you haven't already, call `mark_idle()` to signal availability
2. Call `check_inbox()` to see if there are new task assignments
3. If you receive a termination message, acknowledge and shut down gracefully

Continue the task loop now."""


def handle_worker_termination(
    bootstrap_result: WorkerBootstrapResult,
    user_interface,
    reason: Optional[str] = None,
) -> None:
    """Handle graceful worker termination."""
    from silica.developer.coordination import Result

    result_msg = Result(
        task_id="termination",
        status="terminated",
        summary=f"Worker shutting down: {reason or 'Termination requested'}",
        data={},
    )

    try:
        bootstrap_result.context.send_to_coordinator(result_msg)
        user_interface.handle_system_message(
            f"[yellow]Worker terminating: {reason or 'Requested by coordinator'}[/yellow]",
            markdown=False,
        )
    except Exception as e:
        logger.warning(f"Failed to send termination acknowledgment: {e}")
