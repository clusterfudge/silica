#!/usr/bin/env python3
"""E2E Test: Full task execution flow.

This test:
1. Spawns a worker
2. Sends TaskAssign
3. Receives TaskAck
4. Receives Progress updates
5. Receives Result
6. Verifies worker goes back to Idle

Run with: uv run python scripts/e2e/test_task_flow.py
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
    Progress,
    Result,
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


def spawn_worker(session_name, invite_url, agent_id):
    script_dir = os.path.dirname(__file__)
    result = subprocess.run(
        [
            os.path.join(script_dir, "spawn_worker.sh"),
            session_name,
            invite_url,
            agent_id,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def kill_tmux_session(session_name):
    subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True)


def main():
    print("=" * 60)
    print("E2E Test: Full Task Execution Flow")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    session_name = "e2e-task-flow"

    with test_namespace(deaddrop, prefix="task-flow-test") as ns:
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
            deaddrop, ns, coordinator, room, "TaskWorker"
        )

        agent_id = "task-worker-001"
        context = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=ns["ns"],
            namespace_secret=ns["secret"],
            identity_id=coordinator["id"],
            identity_secret=coordinator["secret"],
            room_id=room["room_id"],
        )

        try:
            # Spawn worker
            if not spawn_worker(session_name, invite_url, agent_id):
                log("FAILED to spawn worker")
                return False
            log("Worker spawned")

            # Wait for initial Idle
            log("Waiting for initial Idle...")
            initial_idle = False
            for _ in range(10):
                messages = context.receive_messages(wait=3, include_room=True)
                for msg in messages:
                    if isinstance(msg.message, Idle):
                        log("✓ Initial Idle received")
                        initial_idle = True
                        break
                if initial_idle:
                    break

            if not initial_idle:
                log("FAILED: No initial Idle")
                return False

            # Send task
            task_id = "test-task-001"
            task = TaskAssign(
                task_id=task_id,
                description="Test task for E2E validation",
                context="This is a test",
            )
            log(f"Sending TaskAssign: {task_id}")
            context.send_message(worker["id"], task)

            # Track expected messages
            received_ack = False
            progress_count = 0
            received_result = False
            final_idle = False

            # Worker polls every 30s, so we need to wait up to 60s for full cycle
            timeout = 60
            start = time.time()

            while time.time() - start < timeout:
                messages = context.receive_messages(wait=3, include_room=True)

                for msg in messages:
                    if isinstance(msg.message, TaskAck):
                        if msg.message.task_id == task_id:
                            log("✓ TaskAck received")
                            received_ack = True

                    elif isinstance(msg.message, Progress):
                        if msg.message.task_id == task_id:
                            progress_count += 1
                            log(
                                f"✓ Progress {progress_count}: "
                                f"{msg.message.message} ({msg.message.progress:.0%})"
                            )

                    elif isinstance(msg.message, Result):
                        if msg.message.task_id == task_id:
                            log(
                                f"✓ Result: {msg.message.status} - {msg.message.summary}"
                            )
                            received_result = True

                    elif isinstance(msg.message, Idle):
                        if msg.message.completed_task_id == task_id:
                            log("✓ Final Idle (after task)")
                            final_idle = True

                # Check if all expected messages received
                if (
                    received_ack
                    and progress_count >= 2
                    and received_result
                    and final_idle
                ):
                    break

            # Verify
            success = True
            if not received_ack:
                log("FAILED: No TaskAck")
                success = False
            if progress_count < 2:
                log(f"FAILED: Only {progress_count} progress messages (expected >= 2)")
                success = False
            if not received_result:
                log("FAILED: No Result")
                success = False
            if not final_idle:
                log("FAILED: No final Idle after task")
                success = False

            if success:
                print()
                print("=" * 60)
                print("✓ Full task execution flow PASSED!")
                print("  - TaskAck received: ✓")
                print(f"  - Progress messages: {progress_count}")
                print("  - Result received: ✓")
                print("  - Worker returned to Idle: ✓")
                print("=" * 60)

            return success

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
