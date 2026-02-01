#!/usr/bin/env python3
"""E2E Test: Coordinator restart maintains worker connections.

This test validates:
1. Start coordinator, spawn workers
2. Workers communicate normally
3. "Restart" coordinator (new session instance with same credentials)
4. Workers still respond to messages

Run with: uv run python scripts/e2e/test_coordinator_restart.py
"""

import os
import sys
import time
import subprocess
import json
import base64
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config import get_e2e_deaddrop, test_namespace
from silica.developer.coordination import (
    CoordinationContext,
    Idle,
    TaskAssign,
    TaskAck,
)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def create_worker_invite(deaddrop, ns, coordinator, room, worker_name):
    worker = deaddrop.create_identity(
        ns=ns["ns"], display_name=worker_name, ns_secret=ns["secret"]
    )
    deaddrop.add_room_member(
        ns=ns["ns"],
        room_id=room["room_id"],
        identity_id=worker["id"],
        secret=coordinator["secret"],
    )
    invite_data = {
        "namespace_id": ns["ns"],
        "namespace_secret": ns["secret"],
        "identity_id": worker["id"],
        "identity_secret": worker["secret"],
        "room_id": room["room_id"],
        "coordinator_id": coordinator["id"],
    }
    invite_json = json.dumps(invite_data)
    invite_encoded = base64.b64encode(invite_json.encode()).decode()
    return worker, f"data:application/json;base64,{invite_encoded}"


def spawn_worker(session_name, invite_url, agent_id, deaddrop_url):
    script_dir = os.path.dirname(__file__)
    env = os.environ.copy()
    env["DEADDROP_URL"] = deaddrop_url
    result = subprocess.run(
        [
            os.path.join(script_dir, "spawn_worker.sh"),
            session_name,
            invite_url,
            agent_id,
        ],
        capture_output=True,
        env=env,
        text=True,
    )
    return result.returncode == 0


def kill_tmux_session(session_name):
    subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True)


def main():
    print("=" * 60)
    print("E2E Test: Coordinator Restart Maintains Worker Connections")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    session_name = "e2e-restart-worker"

    with test_namespace(deaddrop, prefix="restart-test") as ns:
        log(f"Created namespace: {ns['ns'][:8]}...")

        # Create coordinator identity
        coordinator = deaddrop.create_identity(
            ns=ns["ns"], display_name="Coordinator", ns_secret=ns["secret"]
        )
        room = deaddrop.create_room(
            ns=ns["ns"],
            creator_secret=coordinator["secret"],
            display_name="Coordination",
        )
        worker, invite_url = create_worker_invite(
            deaddrop, ns, coordinator, room, "RestartWorker"
        )

        agent_id = "restart-worker-001"

        try:
            # Spawn worker
            if not spawn_worker(session_name, invite_url, agent_id, deaddrop.location):
                log("FAILED to spawn worker")
                return False
            log("Worker spawned")

            # Create initial coordinator context
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
            got_idle = False
            for _ in range(10):
                msgs = context1.receive_messages(wait=3, include_room=True)
                for m in msgs:
                    if isinstance(m.message, Idle):
                        log("✓ Initial Idle received via context1")
                        got_idle = True
                        break
                if got_idle:
                    break

            if not got_idle:
                log("FAILED: No initial Idle")
                return False

            # Simulate coordinator "restart" - create new context with same credentials
            log("Simulating coordinator restart (creating new context)...")
            del context1  # "Kill" the old coordinator

            # Small delay to simulate restart
            time.sleep(1)

            # Create new context (same credentials)
            context2 = CoordinationContext(
                deaddrop=deaddrop,
                namespace_id=ns["ns"],
                namespace_secret=ns["secret"],
                identity_id=coordinator["id"],
                identity_secret=coordinator["secret"],
                room_id=room["room_id"],
            )
            log("✓ New coordinator context created")

            # Send task from new coordinator
            task_id = "post-restart-task"
            task = TaskAssign(
                task_id=task_id,
                description="Task after coordinator restart",
            )
            log(f"Sending task from restarted coordinator: {task_id}")
            context2.send_message(worker["id"], task)

            # Wait for TaskAck from worker
            log("Waiting for TaskAck from worker...")
            got_ack = False
            for _ in range(15):
                msgs = context2.receive_messages(wait=3, include_room=True)
                for m in msgs:
                    if isinstance(m.message, TaskAck):
                        if m.message.task_id == task_id:
                            log("✓ TaskAck received from worker after restart!")
                            got_ack = True
                            break
                if got_ack:
                    break

            if not got_ack:
                log("FAILED: No TaskAck received after coordinator restart")
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
