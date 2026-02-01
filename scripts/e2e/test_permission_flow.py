#!/usr/bin/env python3
"""E2E Test: Permission request/grant flow with real timing.

This test validates:
1. Worker sends PermissionRequest
2. Coordinator receives it
3. Coordinator grants permission
4. Worker receives PermissionResponse

Run with: uv run python scripts/e2e/test_permission_flow.py
"""

import os
import sys
import subprocess
import json
import base64
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config import get_e2e_deaddrop, test_namespace
from silica.developer.coordination import (
    CoordinationContext,
    Idle,
    PermissionRequest,
    PermissionResponse,
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


def spawn_worker(session_name, invite_url, agent_id, deaddrop_url, extra_env=None):
    """Spawn worker with optional extra environment variables."""
    script_dir = os.path.dirname(__file__)
    env = os.environ.copy()
    env["DEADDROP_URL"] = deaddrop_url
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        [
            os.path.join(script_dir, "spawn_worker.sh"),
            session_name,
            invite_url,
            agent_id,
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode == 0


def kill_tmux_session(session_name):
    subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True)


def send_keys_to_tmux(session_name, keys):
    """Send keys to a tmux session."""
    subprocess.run(["tmux", "send-keys", "-t", session_name, keys, "Enter"])


def main():
    print("=" * 60)
    print("E2E Test: Permission Request/Grant Flow")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    session_name = "e2e-permission-worker"

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
            deaddrop, ns, coordinator, room, "PermWorker"
        )

        agent_id = "perm-worker-001"
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
            if not spawn_worker(session_name, invite_url, agent_id, deaddrop.location):
                log("FAILED to spawn worker")
                return False
            log("Worker spawned")

            # Wait for initial Idle
            log("Waiting for initial Idle...")
            got_idle = False
            for _ in range(10):
                msgs = context.receive_messages(wait=3, include_room=True)
                for m in msgs:
                    if isinstance(m.message, Idle):
                        log("✓ Initial Idle received")
                        got_idle = True
                        break
                if got_idle:
                    break

            if not got_idle:
                log("FAILED: No initial Idle")
                return False

            # Send a permission request from coordinator (simulating what worker would send)
            # In a real scenario, the worker would send this when needing permission
            request_id = "test-perm-001"
            log(f"Simulating worker sending PermissionRequest: {request_id}")

            # Worker sends permission request to coordinator
            worker_context = CoordinationContext(
                deaddrop=deaddrop,
                namespace_id=ns["ns"],
                namespace_secret=ns["secret"],
                identity_id=worker["id"],
                identity_secret=worker["secret"],
                room_id=room["room_id"],
                coordinator_id=coordinator["id"],
            )

            perm_request = PermissionRequest(
                request_id=request_id,
                agent_id=agent_id,
                action="shell_execute",
                resource="rm -rf /tmp/test",
                context="Testing permission flow",
            )
            worker_context.send_to_coordinator(perm_request)
            log("✓ PermissionRequest sent")

            # Coordinator receives permission request
            log("Coordinator waiting for PermissionRequest...")
            got_request = False
            for _ in range(10):
                msgs = context.receive_messages(wait=3, include_room=False)
                for m in msgs:
                    if isinstance(m.message, PermissionRequest):
                        log(f"✓ Received PermissionRequest: {m.message.request_id}")
                        got_request = True
                        m.message
                        break
                if got_request:
                    break

            if not got_request:
                log("FAILED: No PermissionRequest received")
                return False

            # Coordinator grants permission
            log("Coordinator granting permission...")
            perm_response = PermissionResponse(
                request_id=request_id,
                decision="allow",
                reason="Approved for testing",
            )
            context.send_message(worker["id"], perm_response)
            log("✓ PermissionResponse sent (allow)")

            # Worker receives permission response
            log("Worker waiting for PermissionResponse...")
            got_response = False
            for _ in range(10):
                msgs = worker_context.receive_messages(wait=3, include_room=False)
                for m in msgs:
                    if isinstance(m.message, PermissionResponse):
                        log(
                            f"✓ Worker received PermissionResponse: {m.message.decision}"
                        )
                        if m.message.decision == "allow":
                            got_response = True
                        break
                if got_response:
                    break

            if not got_response:
                log("FAILED: Worker didn't receive allow response")
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
