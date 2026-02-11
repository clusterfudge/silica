#!/usr/bin/env python3
"""E2E Test: Permission request/grant flow."""

import os
import sys
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
    print("E2E Test: Permission Request/Grant Flow")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    session_name = "e2e-permission"

    with test_namespace(deaddrop, prefix="permission-test") as ns:
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
            "PermWorker",
        )

        agent_id = "perm-worker-001"
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
            log("Worker spawned")

            # Wait for initial Idle
            log("Waiting for initial Idle...")
            for _ in range(10):
                messages = coord_context.receive_messages(wait=3, include_room=True)
                if any(isinstance(m.message, Idle) for m in messages):
                    log("✓ Initial Idle received")
                    break
            else:
                log("FAILED: No initial Idle")
                return False

            # Worker sends permission request
            request_id = "test-perm-001"
            log(f"Simulating worker sending PermissionRequest: {request_id}")
            perm_req = PermissionRequest(
                request_id=request_id,
                task_id="test-task",
                agent_id=agent_id,
                action="shell",
                resource="rm -rf /tmp/test",
                context="Testing permission flow",
            )
            worker_context.send_to_coordinator(perm_req)
            log("✓ PermissionRequest sent")

            # Coordinator receives request
            log("Coordinator waiting for PermissionRequest...")
            received_request = False
            for _ in range(10):
                messages = coord_context.receive_messages(wait=3, include_room=True)
                for msg in messages:
                    if isinstance(msg.message, PermissionRequest):
                        if msg.message.request_id == request_id:
                            log(f"✓ Received PermissionRequest: {request_id}")
                            received_request = True
                            break
                if received_request:
                    break

            if not received_request:
                log("FAILED: Coordinator didn't receive PermissionRequest")
                return False

            # Coordinator grants permission
            log("Coordinator granting permission...")
            perm_resp = PermissionResponse(
                request_id=request_id,
                decision="allow",
                reason="Approved for testing",
            )
            coord_context.send_message(worker["id"], perm_resp)
            log("✓ PermissionResponse sent (allow)")

            # Worker receives response
            log("Worker waiting for PermissionResponse...")
            received_response = False
            for _ in range(10):
                messages = worker_context.receive_messages(wait=3)
                for msg in messages:
                    if isinstance(msg.message, PermissionResponse):
                        if msg.message.request_id == request_id:
                            log(
                                f"✓ Worker received PermissionResponse: {msg.message.decision}"
                            )
                            received_response = True
                            break
                if received_response:
                    break

            if not received_response:
                log("FAILED: Worker didn't receive PermissionResponse")
                return False

            print()
            print("=" * 60)
            print("✓ Permission flow test PASSED!")
            print("  - Worker sent PermissionRequest")
            print("  - Coordinator received request")
            print("  - Coordinator sent PermissionResponse (allow)")
            print("  - Worker received allow response")
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
