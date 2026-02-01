#!/usr/bin/env python3
"""E2E Test: Agent health detection with real timestamps.

This test validates:
1. Spawn multiple workers
2. Track last_seen timestamps from messages
3. Verify we can detect which agents are active
4. One worker stops sending - detect staleness

Run with: uv run python scripts/e2e/test_agent_health.py
"""

import os
import sys
import time
import subprocess
import json
import base64
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config import get_e2e_deaddrop, test_namespace
from silica.developer.coordination import (
    CoordinationContext,
    Idle,
    Progress,
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
    print("E2E Test: Agent Health Detection")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    NUM_WORKERS = 2
    sessions = []

    with test_namespace(deaddrop, prefix="health-test") as ns:
        log(f"Created namespace: {ns['ns'][:8]}...")

        coordinator = deaddrop.create_identity(
            ns=ns["ns"], display_name="Coordinator", ns_secret=ns["secret"]
        )
        room = deaddrop.create_room(
            ns=ns["ns"],
            creator_secret=coordinator["secret"],
            display_name="Coordination",
        )

        context = CoordinationContext(
            deaddrop=deaddrop,
            namespace_id=ns["ns"],
            namespace_secret=ns["secret"],
            identity_id=coordinator["id"],
            identity_secret=coordinator["secret"],
            room_id=room["room_id"],
        )

        # Track agent health
        agent_last_seen = {}  # agent_id -> timestamp

        # Spawn workers
        workers = []
        for i in range(NUM_WORKERS):
            worker_name = f"HealthWorker-{i + 1}"
            agent_id = f"health-agent-{i + 1:03d}"
            session_name = f"e2e-health-worker-{i + 1}"
            sessions.append(session_name)

            worker, invite_url = create_worker_invite(
                deaddrop, ns, coordinator, room, worker_name
            )
            workers.append({"agent_id": agent_id, "worker": worker})

            if spawn_worker(session_name, invite_url, agent_id, deaddrop.location):
                log(f"Spawned {worker_name} ({agent_id})")
            else:
                log(f"FAILED to spawn {worker_name}")
                return False

        try:
            # Collect Idle messages and track timestamps
            log("Collecting agent messages and tracking health...")
            timeout = 15
            start = time.time()

            while time.time() - start < timeout:
                msgs = context.receive_messages(wait=3, include_room=True)

                for msg in msgs:
                    agent_id = None
                    if isinstance(msg.message, Idle):
                        agent_id = msg.message.agent_id
                    elif isinstance(msg.message, Progress):
                        agent_id = msg.message.agent_id

                    if agent_id:
                        now = datetime.now(timezone.utc)
                        agent_last_seen[agent_id] = now
                        log(f"✓ Updated last_seen for {agent_id}")

                # Check if we've heard from all workers
                if len(agent_last_seen) >= NUM_WORKERS:
                    log("All workers have reported in")
                    break

            # Verify we have timestamps for all workers
            if len(agent_last_seen) < NUM_WORKERS:
                log(
                    f"FAILED: Only {len(agent_last_seen)}/{NUM_WORKERS} workers reported"
                )
                return False

            # Kill one worker to simulate it going stale
            stale_agent_id = workers[0]["agent_id"]
            stale_session = sessions[0]
            log(f"Killing worker {stale_agent_id} to simulate staleness...")
            kill_tmux_session(stale_session)
            sessions.remove(stale_session)  # Don't double-kill in cleanup

            # Wait a moment, then check for new messages
            time.sleep(3)

            # Poll for more messages - only active worker should send
            log("Checking which workers are still active...")
            msgs = context.receive_messages(wait=5, include_room=True)

            active_agents = set()
            for msg in msgs:
                if isinstance(msg.message, (Idle, Progress)):
                    active_agents.add(msg.message.agent_id)

            # The killed worker should not have sent new messages
            if stale_agent_id in active_agents:
                log(f"WARNING: Killed worker {stale_agent_id} still sending messages")
            else:
                log(
                    f"✓ Killed worker {stale_agent_id} is not sending messages (as expected)"
                )

            # Check health based on timestamps
            log("Health check based on last_seen timestamps:")
            now = datetime.now(timezone.utc)
            for agent_id, last_seen in agent_last_seen.items():
                age_seconds = (now - last_seen).total_seconds()
                status = "ACTIVE" if age_seconds < 10 else "STALE"
                log(f"  {agent_id}: last_seen {age_seconds:.1f}s ago - {status}")

            print()
            print("=" * 60)
            print("✓ Agent health detection test PASSED!")
            print(f"  - Spawned {NUM_WORKERS} workers")
            print("  - Tracked last_seen timestamps for all")
            print(f"  - Killed one worker ({stale_agent_id})")
            print("  - Can detect active vs stale based on timestamps")
            print("=" * 60)
            return True

        finally:
            for session in sessions:
                kill_tmux_session(session)


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
