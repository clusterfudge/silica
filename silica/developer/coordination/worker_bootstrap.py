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


def claim_invite_and_connect(
    invite_url: Optional[str] = None,
    server_url: Optional[str] = None,
) -> WorkerBootstrapResult:
    """Claim a deaddrop invite and connect to the coordination namespace.

    This is the main entry point for worker bootstrap. It:
    1. Reads invite URL from parameter or environment
    2. Claims the invite to get identity credentials
    3. Extracts namespace and room info from the invite
    4. Creates a CoordinationContext for communication

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

    logger.info(f"Claiming invite from: {invite_url[:50]}...")

    # Claim the invite
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
