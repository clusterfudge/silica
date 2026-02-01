"""Worker permission handling via deaddrop coordination.

This module provides permission callbacks for coordinated workers that
send permission requests to the coordinator instead of prompting locally.
"""

import logging
from typing import Optional

from silica.developer.sandbox import SandboxMode, PermissionResult

logger = logging.getLogger(__name__)

# Type alias for clarity
CoordinationContext = "silica.developer.coordination.client.CoordinationContext"


def create_worker_permission_callback(
    context: CoordinationContext,
    agent_id: str,
    timeout: float = 300.0,  # 5 minutes default
):
    """Create a permission callback for coordinated workers.

    This returns a callback function that sends permission requests to the
    coordinator via deaddrop instead of prompting locally.

    Args:
        context: The worker's CoordinationContext for messaging
        agent_id: This worker's agent ID
        timeout: Timeout in seconds to wait for permission response

    Returns:
        A permission callback function compatible with Sandbox
    """

    def worker_permission_callback(
        action: str,
        resource: str,
        sandbox_mode: SandboxMode,
        action_arguments: dict | None,
        group: Optional[str] = None,
    ) -> PermissionResult:
        """Permission callback that requests permission from coordinator.

        Sends a PermissionRequest to the coordinator and blocks waiting
        for a PermissionResponse.

        Args:
            action: The action being performed (e.g., "read_file", "shell")
            resource: The resource being accessed
            sandbox_mode: Current sandbox mode (largely ignored for workers)
            action_arguments: Optional additional arguments
            group: Optional tool group

        Returns:
            Permission result based on coordinator's decision
        """
        from silica.developer.coordination import PermissionRequest, PermissionResponse

        # Generate a unique request ID
        import uuid

        request_id = str(uuid.uuid4())[:8]

        # Build context string for the coordinator
        context_str = f"Action: {action}\nResource: {resource}"
        if group:
            context_str += f"\nGroup: {group}"
        if action_arguments:
            # Include relevant action arguments
            context_str += f"\nArguments: {action_arguments}"

        # Create and send permission request
        request = PermissionRequest(
            request_id=request_id,
            agent_id=agent_id,
            action=action,
            resource=resource,
            context=context_str,
        )

        logger.info(f"Requesting permission: {action} on {resource}")

        try:
            context.send_to_coordinator(request)
        except Exception as e:
            logger.error(f"Failed to send permission request: {e}")
            # On send failure, deny by default for safety
            return False

        # Poll for response with timeout
        import time

        start_time = time.time()
        poll_interval = 2.0  # Poll every 2 seconds

        while (time.time() - start_time) < timeout:
            try:
                # Only check inbox, not room - permission responses are direct messages
                messages = context.receive_messages(
                    wait=poll_interval, include_room=False
                )

                for msg in messages:
                    if isinstance(msg.message, PermissionResponse):
                        if msg.message.request_id == request_id:
                            decision = msg.message.decision
                            reason = msg.message.reason

                            logger.info(
                                f"Permission response: {decision}"
                                + (f" ({reason})" if reason else "")
                            )

                            # Map decision to PermissionResult
                            if decision == "allow":
                                return True
                            elif decision == "deny":
                                return False
                            elif decision == "always_tool":
                                return "always_tool"
                            elif decision == "always_group":
                                return "always_group"
                            else:
                                # Unknown decision, deny by default
                                return False

            except Exception as e:
                logger.warning(f"Error polling for permission response: {e}")
                # Continue polling on transient errors

        # Timeout - deny by default
        logger.warning(
            f"Permission request timed out after {timeout}s: {action} on {resource}"
        )
        return False

    return worker_permission_callback


def create_worker_permission_rendering_callback():
    """Create a permission rendering callback for coordinated workers.

    Workers don't need to render permission prompts locally since
    they're handled via deaddrop.

    Returns:
        A no-op rendering callback
    """

    def worker_permission_rendering_callback(
        action: str,
        resource: str,
        action_arguments: dict | None,
    ) -> None:
        """No-op rendering callback for workers."""
        # Workers don't render permission prompts - they're handled via deaddrop

    return worker_permission_rendering_callback


def setup_worker_sandbox_permissions(
    sandbox,
    context: CoordinationContext,
    agent_id: str,
    timeout: float = 300.0,
) -> None:
    """Configure a sandbox to use coordination-based permissions.

    This replaces the sandbox's permission callbacks with ones that
    communicate via deaddrop to the coordinator.

    Args:
        sandbox: The Sandbox instance to configure
        context: The worker's CoordinationContext
        agent_id: This worker's agent ID
        timeout: Timeout for permission requests
    """
    sandbox._permission_check_callback = create_worker_permission_callback(
        context=context,
        agent_id=agent_id,
        timeout=timeout,
    )
    sandbox._permission_check_rendering_callback = (
        create_worker_permission_rendering_callback()
    )

    logger.info(f"Configured sandbox for worker {agent_id} with deaddrop permissions")
