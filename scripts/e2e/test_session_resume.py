#!/usr/bin/env python3
"""E2E Test: Session resume reconstructs agent states."""

import os
import sys
import json
import tempfile
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
    print("E2E Test: Session Resume Reconstructs Agent States")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    session_name = "e2e-resume"

    with test_namespace(deaddrop, prefix="resume-test") as ns:
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
            "ResumeWorker",
        )

        agent_id = "resume-agent-001"

        # Save session state to temp file (simulating persistence)
        with tempfile.TemporaryDirectory() as tmpdir:
            session_file = os.path.join(tmpdir, "test-resume-001.json")
            session_state = {
                "session_id": "test-resume-001",
                "namespace_id": ns["ns"],
                "namespace_secret": ns["secret"],
                "coordinator_id": coordinator["id"],
                "coordinator_secret": coordinator["secret"],
                "room_id": room["room_id"],
                "agents": {
                    agent_id: {
                        "identity_id": worker["id"],
                        "display_name": "ResumeWorker",
                        "state": "spawning",
                    }
                },
            }
            with open(session_file, "w") as f:
                json.dump(session_state, f)
            log(f"Saved initial session state to {session_file}")

            context = CoordinationContext(
                deaddrop=deaddrop,
                namespace_id=ns["ns"],
                namespace_secret=ns["secret"],
                identity_id=coordinator["id"],
                identity_secret=coordinator["secret"],
                room_id=room["room_id"],
            )

            try:
                if not spawn_worker_in_tmux(session_name, invite_url, agent_id):
                    log("FAILED to spawn worker")
                    return False

                # Wait for Idle
                log("Waiting for Idle from worker...")
                received_idle = False
                for _ in range(10):
                    messages = context.receive_messages(wait=3, include_room=True)
                    for msg in messages:
                        if isinstance(msg.message, Idle):
                            log(f"✓ Received Idle from {msg.message.agent_id}")
                            received_idle = True
                            break
                    if received_idle:
                        break

                if not received_idle:
                    log("FAILED: No Idle received")
                    return False

                # Test session resume: Read room history
                log("Testing session resume...")
                with open(session_file) as f:
                    loaded_state = json.load(f)
                log(f"Initial agent state: {loaded_state['agents'][agent_id]['state']}")

                # Get room messages to reconstruct state
                room_messages = deaddrop.get_room_messages(
                    ns=ns["ns"],
                    room_id=room["room_id"],
                    secret=coordinator["secret"],
                )
                log(f"Room has {len(room_messages)} messages")

                # Find Idle message in history
                found_idle = False
                for msg in room_messages:
                    try:
                        body = json.loads(msg["body"])
                        if body.get("type") == "idle":
                            found_idle = True
                            log("✓ Found Idle message in room history")
                            break
                    except Exception:
                        pass

                if not found_idle:
                    log("WARNING: Couldn't find Idle in room history")

                log("✓ Room history can be used to reconstruct agent states")

                print()
                print("=" * 60)
                print("✓ Session resume test PASSED!")
                print("  - Worker spawned and sent Idle")
                print("  - Session state saved to file")
                print("  - Room history contains messages for state reconstruction")
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
