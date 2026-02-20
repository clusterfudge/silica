#!/usr/bin/env python3
"""E2E Test: Spawn worker and verify communication.

This test:
1. Creates a coordination session on the deaddrop
2. Spawns a worker in tmux
3. Verifies worker claims invite and sends Idle
4. Cleans up

Run with: uv run python scripts/e2e/test_spawn_worker.py
Set DEADDROP_E2E_REMOTE=1 to test against remote server.
"""

import os
import sys
import time
from datetime import datetime

# Add silica to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config import get_e2e_deaddrop, test_namespace
from worker_utils import create_worker_invite, spawn_worker_in_tmux, kill_tmux_session
from silica.developer.coordination import CoordinationContext, Idle


def log(msg: str):
    """Print timestamped log message."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def main():
    """Run the E2E spawn worker test."""
    print("=" * 60)
    print("E2E Test: Spawn Worker and Verify Communication")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    session_name = "e2e-test-worker"

    with test_namespace(deaddrop, prefix="spawn-worker-test") as ns:
        log(f"Created namespace: {ns['ns'][:8]}...")

        # Create coordinator identity
        coordinator = deaddrop.create_identity(
            ns=ns["ns"],
            display_name="Coordinator",
            ns_secret=ns["secret"],
        )
        log(f"Created coordinator: {coordinator['id'][:8]}...")

        # Create room
        room = deaddrop.create_room(
            ns=ns["ns"],
            creator_secret=coordinator["secret"],
            display_name="Coordination Room",
        )
        log(f"Created room: {room['room_id'][:8]}...")

        # Create worker invite
        worker, invite_url = create_worker_invite(
            deaddrop=deaddrop,
            namespace_id=ns["ns"],
            namespace_secret=ns["secret"],
            coordinator_id=coordinator["id"],
            coordinator_secret=coordinator["secret"],
            room_id=room["room_id"],
            worker_name="Test Worker",
        )
        agent_id = "test-agent-001"
        log(f"Created worker identity: {worker['id'][:8]}...")

        # Create coordinator context for receiving messages
        context = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=ns["ns"],
            namespace_secret=ns["secret"],
            identity_id=coordinator["id"],
            identity_secret=coordinator["secret"],
            room_id=room["room_id"],
        )

        try:
            # Spawn worker (invite URL includes server domain)
            if not spawn_worker_in_tmux(session_name, invite_url, agent_id):
                log("FAILED: Could not spawn worker")
                return False

            log(f"Spawned worker: {session_name}")

            # Wait for Idle message from worker
            log("Waiting for Idle message from worker...")
            timeout = 30
            start = time.time()
            received_idle = False

            while time.time() - start < timeout:
                messages = context.receive_messages(include_room=True)

                for msg in messages:
                    log(f"Received: {msg.message.__class__.__name__}")
                    if isinstance(msg.message, Idle):
                        log(f"✓ Got Idle from agent: {msg.message.agent_id}")
                        if msg.message.agent_id == agent_id:
                            received_idle = True
                            break

                if received_idle:
                    break
                time.sleep(1)

            if not received_idle:
                log(f"FAILED: No Idle message received within {timeout}s")
                return False

            log("✓ Worker spawned and sent Idle message")
            print()
            print("=" * 60)
            print("✓ E2E spawn worker test PASSED!")
            print("=" * 60)
            return True

        finally:
            # Cleanup
            log("Cleaning up tmux session...")
            kill_tmux_session(session_name)


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
