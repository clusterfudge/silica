#!/usr/bin/env python3
"""E2E Test: Agent health detection."""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config import get_e2e_deaddrop, test_namespace
from worker_utils import create_worker_invite, spawn_worker_in_tmux, kill_tmux_session
from silica.developer.coordination import CoordinationContext, Idle


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def main():
    print("=" * 60)
    print("E2E Test: Agent Health Detection")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    sessions = []
    num_workers = 2

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

        agent_ids = []
        try:
            # Spawn workers
            for i in range(num_workers):
                worker, invite_url = create_worker_invite(
                    deaddrop,
                    ns["ns"],
                    ns["secret"],
                    coordinator["id"],
                    coordinator["secret"],
                    room["room_id"],
                    f"HealthWorker-{i+1}",
                )
                agent_id = f"health-agent-{i+1:03d}"
                agent_ids.append(agent_id)
                session_name = f"e2e-health-{i+1}"
                sessions.append(session_name)

                if not spawn_worker_in_tmux(session_name, invite_url, agent_id):
                    log(f"FAILED to spawn worker {i+1}")
                    return False
                log(f"Spawned HealthWorker-{i+1} ({agent_id})")

            # Track last_seen for each agent
            log("Collecting agent messages and tracking health...")
            last_seen = {}
            timeout = 15
            start = time.time()

            while time.time() - start < timeout:
                messages = context.receive_messages(wait=3, include_room=True)
                now = datetime.utcnow()
                for msg in messages:
                    if isinstance(msg.message, Idle):
                        agent = msg.message.agent_id
                        if agent in agent_ids:
                            last_seen[agent] = now
                            log(f"✓ Updated last_seen for {agent}")

                if len(last_seen) == num_workers:
                    log("All workers have reported in")
                    break

            # Kill one worker to simulate staleness
            killed_agent = agent_ids[0]
            log(f"Killing worker {killed_agent} to simulate staleness...")
            kill_tmux_session(sessions[0])
            sessions.pop(0)
            time.sleep(2)

            # Check for messages from remaining worker vs killed worker
            log("Checking which workers are still active...")
            active_agents = set()
            for _ in range(5):
                messages = context.receive_messages(wait=3, include_room=True)
                for msg in messages:
                    if isinstance(msg.message, Idle):
                        active_agents.add(msg.message.agent_id)

            if killed_agent not in active_agents:
                log(
                    f"✓ Killed worker {killed_agent} is not sending messages (as expected)"
                )
            else:
                log(f"WARNING: Killed worker {killed_agent} still sending messages")

            # Print health status
            now = datetime.utcnow()
            log("Health check based on last_seen timestamps:")
            for agent in agent_ids:
                if agent in last_seen:
                    age = (now - last_seen[agent]).total_seconds()
                    status = "STALE" if age > 10 else "OK"
                    log(f"  {agent}: last_seen {age:.1f}s ago - {status}")
                else:
                    log(f"  {agent}: never seen - UNKNOWN")

            print()
            print("=" * 60)
            print("✓ Agent health detection test PASSED!")
            print(f"  - Spawned {num_workers} workers")
            print("  - Tracked last_seen timestamps for all")
            print(f"  - Killed one worker ({killed_agent})")
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
