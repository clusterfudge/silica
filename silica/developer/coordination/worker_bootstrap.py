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


def _create_deaddrop_for_invite(invite_url: str) -> Deaddrop:
    """Create the appropriate Deaddrop client based on the invite URL scheme.

    Supports:
    - http:// / https:// -> Deaddrop.remote()
    - local:// -> Deaddrop.local() using the path embedded in the URL

    Args:
        invite_url: The full invite URL

    Returns:
        Configured Deaddrop client

    Raises:
        RuntimeError: If the URL scheme is not supported
    """
    parsed = urlparse(invite_url)

    if parsed.scheme in ("http", "https"):
        server_url = f"{parsed.scheme}://{parsed.netloc}"
        logger.info(f"Using remote deaddrop: {server_url}")
        return Deaddrop.remote(url=server_url)

    if parsed.scheme == "local":
        # Local deaddrop invite URLs have the format:
        #   local://<path>/join/<invite_id>#<key>
        # For file-based: local:///path/to/deaddrop_dir/join/...
        #   -> netloc is empty, path contains deaddrop dir + /join/...
        # For in-memory: local://:memory:/join/...
        #   -> netloc is ":memory:", path is /join/...
        if parsed.netloc == ":memory:":
            raise RuntimeError(
                "In-memory deaddrop cannot be shared between processes. "
                "Use a file-based local deaddrop (--local) or remote deaddrop "
                "(--remote) for multi-process coordination."
            )

        # Extract the deaddrop directory path from the URL
        # The path is: /path/to/deaddrop_dir/join/<invite_id>
        deaddrop_path = parsed.path.split("/join/")[0]
        if not deaddrop_path:
            raise RuntimeError(
                f"Could not extract deaddrop path from local invite URL: "
                f"{invite_url[:80]}..."
            )
        logger.info(f"Using local deaddrop: {deaddrop_path}")
        return Deaddrop.local(path=deaddrop_path)

    raise RuntimeError(
        f"Unsupported invite URL scheme: {parsed.scheme}. "
        f"Expected http://, https://, or local:// but got: {invite_url[:50]}..."
    )


def claim_invite_and_connect(
    invite_url: Optional[str] = None,
) -> WorkerBootstrapResult:
    """Claim a deaddrop invite and connect to the coordination namespace.

    Supports both remote and local deaddrop backends:
    - Remote: https://server/join/{invite_id}#{key}?room=...&coordinator=...
    - Local:  local:///path/to/.deaddrop/join/{invite_id}#{key}?room=...&coordinator=...

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

    # Parse invite URL and extract coordination metadata
    parsed = urlparse(invite_url)
    query_params = parse_qs(parsed.query)
    room_id = query_params.get("room", [None])[0]
    coordinator_id = query_params.get("coordinator", [None])[0]

    # Create the appropriate deaddrop client based on URL scheme
    deaddrop = _create_deaddrop_for_invite(invite_url)

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


def create_remote_worker_bootstrap_message(
    invite_url: str,
    agent_id: str,
    display_name: str,
    task_description: Optional[str] = None,
) -> str:
    """Create a bootstrap message to send to a remote workspace to start a worker.

    This message is sent via the antennae tell() endpoint to transform a regular
    workspace agent into a coordinated worker.

    Args:
        invite_url: Full deaddrop invite URL with coordination metadata
        agent_id: Assigned agent ID for this worker
        display_name: Human-readable name for the worker
        task_description: Optional initial task to assign

    Returns:
        Message string to send to the workspace agent
    """
    message = f"""**COORDINATION MODE ACTIVATION**

You are being activated as a **Coordinated Worker Agent**.

**Coordination Configuration:**
- Invite URL: {invite_url}
- Agent ID: {agent_id}
- Display Name: {display_name}

**IMPORTANT: Execute these steps immediately:**

1. **Set environment variables** (mentally note these for coordination tools):
   - DEADDROP_INVITE_URL = "{invite_url}"
   - COORDINATION_AGENT_ID = "{agent_id}"

2. **Connect to the coordination namespace** by calling the worker bootstrap:
   - Claim the invite URL to get your identity credentials
   - Join the coordination room
   - Signal that you're ready for tasks

3. **Enter the worker task loop:**
   - Check inbox for task assignments
   - Execute assigned tasks using your full tool capabilities
   - Report progress and results back to coordinator
   - Mark yourself idle when ready for new tasks

**Worker Persona:**
You are now a worker agent under coordinator supervision. Your job is to:
- Execute tasks assigned by the coordinator efficiently
- Report progress and blockers promptly  
- Request permissions when needed for shell commands or file operations
- Complete work and report results accurately

**Begin by connecting to the coordination namespace using the invite URL above.**
"""

    if task_description:
        message += f"""
**Initial Task:**
{task_description}

After connecting, immediately begin working on this task.
"""

    return message


def create_worker_termination_message(
    agent_id: str, reason: Optional[str] = None
) -> str:
    """Create a termination message to send to a remote worker.

    Args:
        agent_id: The agent ID of the worker to terminate
        reason: Optional reason for termination

    Returns:
        Message string to send to the workspace agent
    """
    reason_text = reason or "Coordination session ending"

    return f"""**WORKER TERMINATION REQUEST**

Agent ID: {agent_id}
Reason: {reason_text}

**Required Actions:**
1. Complete any in-progress work or save state
2. Send a final status update to the coordinator
3. Acknowledge termination
4. Shut down gracefully

This coordination session is ending. Thank you for your work.
"""
