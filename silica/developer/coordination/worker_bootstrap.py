"""Worker bootstrap - claim invite and connect to coordination namespace.

This module handles the startup flow for worker agents spawned by a coordinator.
Workers detect their coordination context via environment variables and connect
to the coordinator's deaddrop namespace.
"""

import os
import logging
from typing import Optional
from dataclasses import dataclass

from deadrop import Deaddrop

from .client import CoordinationContext

logger = logging.getLogger(__name__)


# Environment variable names
DEADDROP_INVITE_URL = "DEADDROP_INVITE_URL"
DEADDROP_SERVER_URL = "DEADDROP_SERVER_URL"
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
    """Check if coordination invite URL is in environment.

    Returns:
        Invite URL if present, None otherwise
    """
    return os.environ.get(DEADDROP_INVITE_URL)


def get_agent_id_from_env() -> Optional[str]:
    """Get agent ID from environment.

    Returns:
        Agent ID if present, None otherwise
    """
    return os.environ.get(COORDINATION_AGENT_ID)


def is_coordinated_worker() -> bool:
    """Check if this agent should run as a coordinated worker.

    Returns:
        True if coordination environment variables are set
    """
    return get_invite_from_env() is not None


def _parse_data_url_invite(invite_url: str) -> dict:
    """Parse a data: URL containing base64-encoded JSON credentials.

    The coordinator's spawn_agent creates invites in this format:
    data:application/json;base64,<base64-encoded-json>

    Args:
        invite_url: The data URL to parse

    Returns:
        Dictionary with credential fields

    Raises:
        ValueError: If URL format is invalid
    """
    import json
    import base64

    if not invite_url.startswith("data:application/json;base64,"):
        raise ValueError(f"Invalid data URL format: {invite_url[:50]}...")

    # Extract the base64 part after the prefix
    prefix = "data:application/json;base64,"
    encoded_data = invite_url[len(prefix) :]

    try:
        decoded_bytes = base64.b64decode(encoded_data)
        return json.loads(decoded_bytes.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to decode invite data: {e}") from e


def claim_invite_and_connect(
    invite_url: Optional[str] = None,
    server_url: Optional[str] = None,
) -> WorkerBootstrapResult:
    """Claim a deaddrop invite and connect to the coordination namespace.

    This is the main entry point for worker bootstrap. It:
    1. Reads invite URL from parameter or environment
    2. Parses credentials (from data: URL or deaddrop invite)
    3. Creates a CoordinationContext for communication

    The invite can be:
    - A data: URL with base64-encoded JSON (from spawn_agent)
    - A standard deaddrop invite URL (claimed from deaddrop server)

    Args:
        invite_url: Invite URL (defaults to DEADDROP_INVITE_URL env var)
        server_url: Optional server URL override

    Returns:
        WorkerBootstrapResult with context and connection info

    Raises:
        RuntimeError: If invite URL not provided or invalid
        ConnectionError: If unable to connect to deaddrop server
    """
    # Get invite URL
    invite_url = invite_url or get_invite_from_env()
    if not invite_url:
        raise RuntimeError(
            f"No invite URL provided. Set {DEADDROP_INVITE_URL} environment variable "
            "or pass invite_url parameter."
        )

    # Get server URL
    server_url = server_url or os.environ.get(DEADDROP_SERVER_URL)

    # Create deaddrop client
    if server_url:
        deaddrop = Deaddrop(server_url)
    else:
        # Default deaddrop server
        deaddrop = Deaddrop()

    # Parse invite - handle different formats
    if invite_url.startswith("data:"):
        # Coordinator-generated invite with embedded credentials
        logger.info("Parsing embedded credentials from data URL...")
        try:
            claim_result = _parse_data_url_invite(invite_url)
        except ValueError as e:
            raise RuntimeError(f"Invalid invite data: {e}") from e
    else:
        # Standard deaddrop invite URL - claim from server
        logger.info(f"Claiming invite from server: {invite_url[:50]}...")
        try:
            claim_result = deaddrop.claim_invite(invite_url)
        except Exception as e:
            raise ConnectionError(f"Failed to claim invite: {e}") from e

    # Extract credentials from claim result
    identity_id = claim_result.get("identity_id") or claim_result.get("id")
    identity_secret = claim_result.get("identity_secret") or claim_result.get("secret")
    namespace_id = claim_result.get("namespace_id") or claim_result.get("ns")
    namespace_secret = claim_result.get("namespace_secret") or claim_result.get(
        "ns_secret"
    )
    display_name = claim_result.get("display_name", "Worker")

    if not all([identity_id, identity_secret, namespace_id]):
        raise RuntimeError(
            f"Invalid claim result, missing required fields: {claim_result}"
        )

    # Look up room info - coordinator puts workers in the coordination room
    # The invite metadata should include the room_id and coordinator_id
    room_id = claim_result.get("room_id")
    coordinator_id = claim_result.get("coordinator_id")

    # If not in invite, try to get from namespace info
    if not room_id or not coordinator_id:
        # Get namespace info to find room
        try:
            ns_info = deaddrop.get_namespace(
                ns=namespace_id,
                secret=namespace_secret,
            )
            # Look for a "coordination" room
            if "rooms" in ns_info:
                for room in ns_info["rooms"]:
                    if room.get("name") == "coordination":
                        room_id = room.get("id")
                        break
        except Exception:
            logger.warning("Could not retrieve namespace info for room discovery")

    # Create coordination context
    context = CoordinationContext(
        deaddrop=deaddrop,
        namespace_id=namespace_id,
        namespace_secret=namespace_secret,
        identity_id=identity_id,
        identity_secret=identity_secret,
        room_id=room_id,
        coordinator_id=coordinator_id,
    )

    # Get agent ID from environment or generate from identity
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
    """Set up worker coordination tools with the bootstrap context.

    This configures the worker_coordination module's global context
    so the tools (check_inbox, send_to_coordinator, etc.) work.

    Args:
        bootstrap_result: Result from claim_invite_and_connect()
    """
    from silica.developer.tools.worker_coordination import set_worker_context

    set_worker_context(
        context=bootstrap_result.context,
        agent_id=bootstrap_result.agent_id,
    )


def bootstrap_worker(
    invite_url: Optional[str] = None,
    server_url: Optional[str] = None,
) -> Optional[WorkerBootstrapResult]:
    """Full worker bootstrap - connect and set up tools.

    Convenience function that combines claim_invite_and_connect()
    and setup_worker_tools().

    Args:
        invite_url: Optional invite URL override
        server_url: Optional server URL override

    Returns:
        WorkerBootstrapResult if successful, None if not a coordinated worker

    Raises:
        RuntimeError, ConnectionError: If bootstrap fails
    """
    # Check if we should bootstrap
    if not invite_url and not is_coordinated_worker():
        return None

    # Connect
    result = claim_invite_and_connect(
        invite_url=invite_url,
        server_url=server_url,
    )

    # Set up tools
    setup_worker_tools(result)

    return result


def get_worker_persona():
    """Get the worker persona for coordinated workers.

    Returns:
        Persona object configured for worker agents
    """
    from silica.developer import personas
    from silica.developer.personas.worker_agent import PERSONA as WORKER_PERSONA
    from silica.developer.utils import wrap_text_as_content_block
    from pathlib import Path

    # Create a Persona object with the worker persona prompt
    return personas.Persona(
        system_block=wrap_text_as_content_block(WORKER_PERSONA),
        base_directory=Path("~/.silica/personas/coordination_worker").expanduser(),
    )


def integrate_worker_startup(
    user_interface,
) -> Optional[WorkerBootstrapResult]:
    """Integrate worker coordination into agent startup.

    This is the main entry point called from hdev.py when starting an agent.
    It checks for coordination environment variables and bootstraps if present.

    Args:
        user_interface: The user interface for status messages

    Returns:
        WorkerBootstrapResult if this is a coordinated worker, None otherwise
    """
    if not is_coordinated_worker():
        return None

    # Show coordination status
    user_interface.handle_system_message(
        "[bold cyan]🤝 Coordination Mode Detected[/bold cyan]\n"
        "Connecting to coordinator...",
        markdown=False,
    )

    try:
        result = bootstrap_worker()

        if result:
            # Send Idle message to coordinator to signal we're ready
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
    """Generate the initial prompt for a worker agent.

    This prompt kicks off the task execution loop by having the worker
    check their inbox for task assignments.

    Args:
        bootstrap_result: The bootstrap result with connection info

    Returns:
        Initial prompt string to start the worker agent loop
    """
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
    """Create a prompt that reminds the worker to continue the task loop.

    This can be injected into the conversation when the worker seems
    to have completed a task but hasn't checked for the next one.

    Returns:
        Prompt string to continue the task loop
    """
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
    """Handle graceful worker termination.

    Called when the worker receives a termination message or needs to shut down.

    Args:
        bootstrap_result: The bootstrap result with connection info
        user_interface: The user interface for status messages
        reason: Optional reason for termination
    """
    from silica.developer.coordination import Result

    # Send final result acknowledging termination
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
