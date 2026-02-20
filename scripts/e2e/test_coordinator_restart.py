#!/usr/bin/env python3
"""E2E Test: Coordinator restart maintains worker connections."""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config import get_e2e_deaddrop, test_namespace
from worker_utils import create_worker_invite, spawn_worker_in_tmux, kill_tmux_session
from silica.developer.coordination import CoordinationContext, Idle, TaskAssign, TaskAck


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def main():
    print("=" * 60)
    print("E2E Test: Coordinator Restart Maintains Worker Connections")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    session_name = "e2e-restart"

    with test_namespace(deaddrop, prefix="restart-test") as ns:
        log(f"Created namespace: {ns['ns'][:8]}...")

        coordinator = deaddrop.create_identity(
            ns=ns["ns"], display_name="Coordinator", ns_secret=ns["secret"]
        )
        room = deaddrop.create_room(
            ns=ns["ns"],
            creator_secret=coordinator["secret"],
            display_name="Coordination",
        )
        worker, invite_url = create_worker_invite(
            deaddrop,
            ns["ns"],
            ns["secret"],
            coordinator["id"],
            coordinator["secret"],
            room["room_id"],
            "RestartWorker",
        )

        agent_id = "restart-worker-001"

        try:
            if not spawn_worker_in_tmux(session_name, invite_url, agent_id):
                log("FAILED to spawn worker")
                return False
            log("Worker spawned")

            # Create first coordinator context
            log("Creating initial coordinator context...")
            context1 = CoordinationContext(
                deaddrop=deaddrop,
                namespace_id=ns["ns"],
                namespace_secret=ns["secret"],
                identity_id=coordinator["id"],
                identity_secret=coordinator["secret"],
                room_id=room["room_id"],
            )

            # Wait for initial Idle
            log("Waiting for initial Idle...")
            for _ in range(10):
                messages = context1.receive_messages(include_room=True)
                if any(isinstance(m.message, Idle) for m in messages):
                    log("✓ Initial Idle received via context1")
                    break
                time.sleep(1)
            else:
                log("FAILED: No initial Idle")
                return False

            # Simulate coordinator restart by creating new context
            log("Simulating coordinator restart (creating new context)...")
            time.sleep(1)
            context2 = CoordinationContext(
                deaddrop=deaddrop,
                namespace_id=ns["ns"],
                namespace_secret=ns["secret"],
                identity_id=coordinator["id"],
                identity_secret=coordinator["secret"],
                room_id=room["room_id"],
            )
            log("✓ New coordinator context created")

            # Send task from restarted coordinator
            task_id = "post-restart-task"
            log(f"Sending task from restarted coordinator: {task_id}")
            task = TaskAssign(
                task_id=task_id,
                description="Task after coordinator restart",
                context="Testing restart resilience",
            )
            context2.send_message(worker["id"], task)

            # Wait for TaskAck
            log("Waiting for TaskAck from worker...")
            received_ack = False
            for _ in range(15):
                messages = context2.receive_messages(include_room=True)
                for msg in messages:
                    if isinstance(msg.message, TaskAck):
                        if msg.message.task_id == task_id:
                            log("✓ TaskAck received from worker after restart!")
                            received_ack = True
                            break
                if received_ack:
                    break
                time.sleep(1)

            if not received_ack:
                log("FAILED: No TaskAck after restart")
                return False

            print()
            print("=" * 60)
            print("✓ Coordinator restart test PASSED!")
            print("  - Worker spawned and sent Idle")
            print("  - Coordinator 'restarted' (new context)")
            print("  - Task sent from restarted coordinator")
            print("  - Worker still responds with TaskAck")
            print("=" * 60)
            return True

        finally:
            kill_tmux_session(session_name)


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
