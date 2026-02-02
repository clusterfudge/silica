#!/usr/bin/env python3
"""E2E Test: Spawn multiple workers."""

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
    print("E2E Test: Spawn Multiple Workers")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    sessions = []
    num_workers = 3

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

        try:
            # Spawn workers
            expected_agents = []
            for i in range(num_workers):
                worker, invite_url = create_worker_invite(
                    deaddrop,
                    ns["ns"],
                    ns["secret"],
                    coordinator["id"],
                    coordinator["secret"],
                    room["room_id"],
                    f"Worker-{i+1}",
                )
                agent_id = f"agent-{i+1:03d}"
                session_name = f"e2e-multi-{i+1}"
                sessions.append(session_name)
                expected_agents.append(agent_id)

                if not spawn_worker_in_tmux(session_name, invite_url, agent_id):
                    log(f"FAILED to spawn worker {i+1}")
                    return False
                log(f"Spawned Worker-{i+1} ({agent_id})")

            # Wait for all Idle messages
            log(f"Waiting for {num_workers} Idle messages...")
            received_agents = set()
            timeout = 30
            start = time.time()

            while time.time() - start < timeout and len(received_agents) < num_workers:
                messages = context.receive_messages(wait=3, include_room=True)
                for msg in messages:
                    if isinstance(msg.message, Idle):
                        agent = msg.message.agent_id
                        if agent in expected_agents and agent not in received_agents:
                            received_agents.add(agent)
                            log(f"✓ Received Idle from {agent}")

            if len(received_agents) < num_workers:
                log(
                    f"FAILED: Only received {len(received_agents)}/{num_workers} Idle messages"
                )
                return False

            print()
            print("=" * 60)
            print(f"✓ All {num_workers} workers spawned and sent Idle!")
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
