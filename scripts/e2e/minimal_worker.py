#!/usr/bin/env python3
"""Minimal worker process for E2E testing.

This script simulates a worker agent that:
1. Claims the invite from DEADDROP_INVITE_URL
2. Connects to the coordination namespace
3. Sends Idle message to coordinator
4. Waits for messages and responds

Run with: DEADDROP_INVITE_URL=data:... python minimal_worker.py
"""

import json
import os
import sys
import time
import base64
from datetime import datetime

# Add silica to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from deadrop import Deaddrop
from silica.developer.coordination import (
    CoordinationContext,
    Idle,
    TaskAck,
    Progress,
    Result,
)


def log(msg: str):
    """Print timestamped log message."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def parse_invite_url() -> dict:
    """Parse the DEADDROP_INVITE_URL environment variable.

    Returns:
        Dict with namespace_id, namespace_secret, identity_id, identity_secret,
        room_id, coordinator_id
    """
    invite_url = os.environ.get("DEADDROP_INVITE_URL")
    if not invite_url:
        raise ValueError("DEADDROP_INVITE_URL environment variable not set")

    # Parse data: URL format
    if invite_url.startswith("data:"):
        # data:application/json;base64,<base64-encoded-json>
        parts = invite_url.split(",", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid data: URL format: {invite_url[:50]}...")
        encoded = parts[1]
        decoded = base64.b64decode(encoded).decode()
        return json.loads(decoded)

    raise ValueError(f"Unsupported invite URL format: {invite_url[:50]}...")


def get_deaddrop_url() -> str:
    """Get the deaddrop server URL from environment or default."""
    return os.environ.get("DEADDROP_URL", "http://127.0.0.1:8765")


def main():
    """Main worker loop."""
    log("Worker starting...")

    # Parse invite
    try:
        invite = parse_invite_url()
        log(f"Parsed invite for namespace {invite['namespace_id'][:8]}...")
    except Exception as e:
        log(f"ERROR: Failed to parse invite: {e}")
        sys.exit(1)

    # Connect to deaddrop
    deaddrop_url = get_deaddrop_url()
    log(f"Connecting to {deaddrop_url}")
    deaddrop = Deaddrop.remote(url=deaddrop_url)

    # Create coordination context
    context = CoordinationContext(
        deaddrop=deaddrop,
        namespace_id=invite["namespace_id"],
        namespace_secret=invite["namespace_secret"],
        identity_id=invite["identity_id"],
        identity_secret=invite["identity_secret"],
        room_id=invite.get("room_id"),
        coordinator_id=invite.get("coordinator_id"),
    )

    agent_id = os.environ.get("COORDINATION_AGENT_ID", "unknown-agent")
    log(f"Agent ID: {agent_id}")

    # Send Idle message
    log("Sending Idle message to room...")
    try:
        context.broadcast(Idle(agent_id=agent_id))
        log("✓ Idle message sent")
    except Exception as e:
        log(f"ERROR sending Idle: {e}")
        # Continue anyway - might not have room

    # Main loop - poll for messages
    log("Entering message loop...")
    running = True
    while running:
        try:
            # Poll for messages (5s timeout for faster E2E testing)
            poll_timeout = int(os.environ.get("WORKER_POLL_TIMEOUT", "5"))
            messages = context.receive_messages(wait=poll_timeout, include_room=True)

            for msg in messages:
                log(
                    f"Received: {msg.message.__class__.__name__} from {msg.from_id[:8]}..."
                )

                # Handle different message types
                if hasattr(msg.message, "type"):
                    msg_type = msg.message.type

                    if msg_type == "task_assign":
                        # Acknowledge task
                        log(f"Got task: {msg.message.task_id}")
                        context.send_to_coordinator(
                            TaskAck(
                                task_id=msg.message.task_id,
                                agent_id=agent_id,
                            )
                        )
                        log("Sent TaskAck")

                        # Simulate work with progress
                        for i in range(3):
                            time.sleep(1)
                            context.broadcast(
                                Progress(
                                    task_id=msg.message.task_id,
                                    agent_id=agent_id,
                                    progress=(i + 1) / 3,
                                    message=f"Step {i + 1}/3",
                                )
                            )
                            log(f"Sent Progress {i + 1}/3")

                        # Complete task
                        context.send_to_coordinator(
                            Result(
                                task_id=msg.message.task_id,
                                status="success",
                                summary="Task completed by minimal worker",
                            )
                        )
                        log("Sent Result (success)")

                        # Go idle
                        context.broadcast(
                            Idle(
                                agent_id=agent_id,
                                completed_task_id=msg.message.task_id,
                            )
                        )
                        log("Sent Idle after task")

                    elif msg_type == "terminate":
                        log(f"Received terminate: {msg.message.reason}")
                        context.send_to_coordinator(
                            Result(
                                task_id="",
                                status="terminated",
                                summary=f"Terminated: {msg.message.reason}",
                            )
                        )
                        running = False

                    elif msg_type == "permission_response":
                        log(
                            f"Permission response: {msg.message.decision} "
                            f"for {msg.message.request_id}"
                        )

        except KeyboardInterrupt:
            log("Interrupted, exiting...")
            running = False
        except Exception as e:
            log(f"ERROR in loop: {e}")
            time.sleep(5)  # Back off on error

    log("Worker exiting.")


if __name__ == "__main__":
    main()
