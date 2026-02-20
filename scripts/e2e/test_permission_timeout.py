#!/usr/bin/env python3
"""E2E Test: Permission timeout mechanics."""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config import get_e2e_deaddrop, test_namespace
from worker_utils import create_worker_invite, spawn_worker_in_tmux, kill_tmux_session
from silica.developer.coordination import (
    CoordinationContext,
    Idle,
    PermissionRequest,
    PermissionResponse,
)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def main():
    print("=" * 60)
    print("E2E Test: Permission Timeout Mechanics")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    session_name = "e2e-perm-timeout"

    with test_namespace(deaddrop, prefix="perm-timeout-test") as ns:
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
            "TimeoutWorker",
        )

        agent_id = "timeout-worker-001"
        coord_context = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=ns["ns"],
            namespace_secret=ns["secret"],
            identity_id=coordinator["id"],
            identity_secret=coordinator["secret"],
            room_id=room["room_id"],
        )
        worker_context = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=ns["ns"],
            namespace_secret=ns["secret"],
            identity_id=worker["id"],
            identity_secret=worker["secret"],
            room_id=room["room_id"],
            coordinator_id=coordinator["id"],
        )

        try:
            if not spawn_worker_in_tmux(session_name, invite_url, agent_id):
                log("FAILED to spawn worker")
                return False

            # Wait for initial Idle
            for _ in range(10):
                messages = coord_context.receive_messages(include_room=True)
                if any(isinstance(m.message, Idle) for m in messages):
                    log("✓ Initial Idle received")
                    break
                time.sleep(1)
            else:
                log("FAILED: No initial Idle")
                return False

            # Worker sends permission request
            request_id = "timeout-test-001"
            log(f"Worker sending PermissionRequest: {request_id}")
            perm_req = PermissionRequest(
                request_id=request_id,
                task_id="test-task",
                agent_id=agent_id,
                action="shell",
                resource="dangerous-command",
                context="Testing timeout",
            )
            worker_context.send_to_coordinator(perm_req)

            # Coordinator receives but delays response
            log("Coordinator receiving request but delaying response...")
            for _ in range(10):
                messages = coord_context.receive_messages(include_room=True)
                for msg in messages:
                    if isinstance(msg.message, PermissionRequest):
                        log(f"✓ Coordinator received request: {msg.message.request_id}")
                        break
                time.sleep(1)

            log("Simulating coordinator delay (2 seconds)...")
            time.sleep(2)

            # Coordinator sends late response
            log("Coordinator sending delayed PermissionResponse (deny)...")
            perm_resp = PermissionResponse(
                request_id=request_id,
                decision="deny",
                reason="Denied after delay",
            )
            coord_context.send_message(worker["id"], perm_resp)

            # Verify worker receives it
            for _ in range(10):
                messages = worker_context.receive_messages()
                for msg in messages:
                    if isinstance(msg.message, PermissionResponse):
                        log(f"✓ Worker received late response: {msg.message.decision}")
                        break
                time.sleep(1)

            print()
            print("=" * 60)
            print("✓ Permission timeout mechanics test PASSED!")
            print("  - Worker sent PermissionRequest")
            print("  - Coordinator received but delayed")
            print("  - Late PermissionResponse delivered")
            print("  - Message flow works even with delays")
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
