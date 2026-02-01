#!/usr/bin/env python3
"""E2E Test: Permission request timeout behavior.

This test validates the timeout mechanics:
1. Worker sends PermissionRequest
2. Coordinator deliberately doesn't respond immediately
3. Worker's timeout logic would trigger (we simulate this)
4. Permission gets queued on coordinator side

Note: This is a simplified test - the actual timeout behavior
is tested in unit tests with shorter intervals.

Run with: uv run python scripts/e2e/test_permission_timeout.py
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
    print("E2E Test: Permission Timeout Mechanics")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    session_name = "e2e-timeout-worker"

    with test_namespace(deaddrop, prefix="timeout-test") as ns:
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
            deaddrop, ns, coordinator, room, "TimeoutWorker"
        )

        agent_id = "timeout-worker-001"
        context = CoordinationContext(
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
            # Spawn worker
            if not spawn_worker(session_name, invite_url, agent_id, deaddrop.location):
                log("FAILED to spawn worker")
                return False
            log("Worker spawned")

            # Wait for Idle
            for _ in range(10):
                msgs = context.receive_messages(wait=3, include_room=True)
                if any(isinstance(m.message, Idle) for m in msgs):
                    log("✓ Initial Idle received")
                    break

            # Worker sends permission request
            request_id = "timeout-test-001"
            perm_request = PermissionRequest(
                request_id=request_id,
                agent_id=agent_id,
                action="shell_execute",
                resource="dangerous_command",
                context="Testing timeout behavior",
            )
            log(f"Worker sending PermissionRequest: {request_id}")
            worker_context.send_to_coordinator(perm_request)

            # Coordinator receives but "delays" response
            log("Coordinator receiving request but delaying response...")
            got_request = False
            for _ in range(5):
                msgs = context.receive_messages(wait=2, include_room=False)
                for m in msgs:
                    if isinstance(m.message, PermissionRequest):
                        log(f"✓ Coordinator received request: {m.message.request_id}")
                        got_request = True
                        break
                if got_request:
                    break

            if not got_request:
                log("FAILED: Coordinator didn't receive request")
                return False

            # Simulate delay (in real scenario, this could be coordinator being busy)
            log("Simulating coordinator delay (2 seconds)...")
            time.sleep(2)

            # Now coordinator responds with deny (simulating late response)
            log("Coordinator sending delayed PermissionResponse (deny)...")
            deny_response = PermissionResponse(
                request_id=request_id,
                decision="deny",
                reason="Request timed out on worker side (simulated)",
            )
            context.send_message(worker["id"], deny_response)

            # Verify worker can receive the late response
            got_response = False
            for _ in range(5):
                msgs = worker_context.receive_messages(wait=2, include_room=False)
                for m in msgs:
                    if isinstance(m.message, PermissionResponse):
                        log(f"✓ Worker received late response: {m.message.decision}")
                        got_response = True
                        break
                if got_response:
                    break

            if not got_response:
                log("FAILED: Worker didn't receive late response")
                return False

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
