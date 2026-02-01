#!/usr/bin/env python3
"""E2E Test: Spawn multiple workers simultaneously.

This test:
1. Creates a coordination session
2. Spawns 3 workers in parallel
3. Verifies all send Idle messages
4. Cleans up

Run with: uv run python scripts/e2e/test_multiple_workers.py
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
from silica.developer.coordination import CoordinationContext, Idle


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def create_worker_invite(deaddrop, ns, coordinator, room, worker_name):
    worker = deaddrop.create_identity(
        ns=ns["ns"],
        display_name=worker_name,
        ns_secret=ns["secret"],
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
    print("E2E Test: Spawn Multiple Workers")
    print("=" * 60)

    NUM_WORKERS = 3
    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    sessions = []

    with test_namespace(deaddrop, prefix="multi-worker-test") as ns:
        log(f"Created namespace: {ns['ns'][:8]}...")

        coordinator = deaddrop.create_identity(
            ns=ns["ns"], display_name="Coordinator", ns_secret=ns["secret"]
        )
        room = deaddrop.create_room(
            ns=ns["ns"],
            creator_secret=coordinator["secret"],
            display_name="Coordination",
        )
        log("Created coordinator and room")

        context = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=ns["ns"],
            namespace_secret=ns["secret"],
            identity_id=coordinator["id"],
            identity_secret=coordinator["secret"],
            room_id=room["room_id"],
        )

        # Spawn workers
        workers = []
        for i in range(NUM_WORKERS):
            worker_name = f"Worker-{i + 1}"
            agent_id = f"agent-{i + 1:03d}"
            session_name = f"e2e-multi-worker-{i + 1}"
            sessions.append(session_name)

            worker, invite_url = create_worker_invite(
                deaddrop, ns, coordinator, room, worker_name
            )
            workers.append({"agent_id": agent_id, "idle_received": False})

            if spawn_worker(session_name, invite_url, agent_id, deaddrop.location):
                log(f"Spawned {worker_name} ({agent_id})")
            else:
                log(f"FAILED to spawn {worker_name}")
                return False

        # Wait for all Idle messages
        log(f"Waiting for {NUM_WORKERS} Idle messages...")
        timeout = 30
        start = time.time()

        while time.time() - start < timeout:
            messages = context.receive_messages(wait=5, include_room=True)

            for msg in messages:
                if isinstance(msg.message, Idle):
                    agent_id = msg.message.agent_id
                    for w in workers:
                        if w["agent_id"] == agent_id and not w["idle_received"]:
                            w["idle_received"] = True
                            log(f"✓ Received Idle from {agent_id}")

            # Check if all received
            if all(w["idle_received"] for w in workers):
                break

        # Verify
        all_received = all(w["idle_received"] for w in workers)
        received_count = sum(1 for w in workers if w["idle_received"])

        for session in sessions:
            kill_tmux_session(session)

        if all_received:
            print()
            print("=" * 60)
            print(f"✓ All {NUM_WORKERS} workers spawned and sent Idle!")
            print("=" * 60)
            return True
        else:
            log(f"FAILED: Only {received_count}/{NUM_WORKERS} workers sent Idle")
            return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
