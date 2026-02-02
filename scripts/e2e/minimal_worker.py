#!/usr/bin/env python3
"""Minimal worker process for E2E testing.

This script simulates a worker agent that:
1. Claims the invite from DEADDROP_INVITE_URL
2. Connects to the coordination namespace
3. Sends Idle message to coordinator
4. Waits for messages and responds

Run with: DEADDROP_INVITE_URL=<url> python minimal_worker.py

The invite URL can be:
- A data: URL (legacy): data:application/json;base64,<encoded-json>
- A deaddrop invite URL: https://server/join/{id}#{key}?room=...&coordinator=...
"""

import os
import sys
import time
from datetime import datetime

# Add silica to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from silica.developer.coordination import (
    Idle,
    TaskAck,
    Progress,
    Result,
)
from silica.developer.coordination.worker_bootstrap import claim_invite_and_connect


def log(msg: str):
    """Print timestamped log message."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def main():
    """Main worker loop."""
    log("Worker starting...")

    # Bootstrap: parse invite and connect
    try:
        bootstrap = claim_invite_and_connect()
        log(f"Connected to namespace {bootstrap.namespace_id[:8]}...")
        log(f"Agent ID: {bootstrap.agent_id}")
    except Exception as e:
        log(f"ERROR: Failed to bootstrap: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    context = bootstrap.context
    agent_id = bootstrap.agent_id

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
            import traceback

            traceback.print_exc()
            time.sleep(5)  # Back off on error

    log("Worker exiting.")


if __name__ == "__main__":
    main()
