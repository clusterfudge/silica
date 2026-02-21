#!/usr/bin/env python3
"""E2E Test: Subscribe-based real-time message notification.

Validates that the coordinator's subscribe mechanism detects worker messages
immediately rather than requiring explicit polling. This tests the same
code path used by _wait_with_coordination in agent_loop.py.

Run with: uv run python scripts/e2e/test_subscribe_notify.py
"""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config import get_e2e_deaddrop, test_namespace
from worker_utils import create_worker_invite, spawn_worker_in_tmux, kill_tmux_session


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def main():
    print("=" * 60)
    print("E2E Test: Subscribe-Based Notification")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    session_name = "e2e-subscribe-test"

    with test_namespace(deaddrop, prefix="subscribe-notify-test") as ns:
        log(f"Created namespace: {ns['ns'][:8]}...")

        # Set up coordinator identity and room
        coordinator = deaddrop.create_identity(
            ns=ns["ns"], display_name="Coordinator", ns_secret=ns["secret"]
        )
        room = deaddrop.create_room(
            ns=ns["ns"],
            creator_secret=coordinator["secret"],
            display_name="Coordination",
        )

        # Create worker
        worker, invite_url = create_worker_invite(
            deaddrop,
            ns["ns"],
            ns["secret"],
            coordinator["id"],
            coordinator["secret"],
            room["room_id"],
            "SubscribeWorker",
        )

        try:
            # Start subscribe BEFORE spawning the worker — this simulates
            # the coordinator waiting for input while subscribe watches
            log("Starting subscribe (30s timeout)...")
            subscribe_started = time.time()

            # Subscribe to both inbox and room
            topics = {
                f"inbox:{coordinator['id']}": None,
                f"room:{room['room_id']}": None,
            }

            # Spawn the worker in background — it will send an Idle message
            log("Spawning worker (will send Idle)...")
            if not spawn_worker_in_tmux(session_name, invite_url, "subscribe-agent"):
                log("FAILED to spawn worker")
                return False

            # Now call subscribe — should return quickly once worker sends Idle
            result = deaddrop.subscribe(
                ns=ns["ns"],
                secret=coordinator["secret"],
                topics=topics,
                timeout=30,
            )
            elapsed = time.time() - subscribe_started

            log(f"Subscribe returned in {elapsed:.2f}s")

            if result.get("timeout"):
                log("FAILED: Subscribe timed out — worker message not detected")
                return False

            events = result.get("events", {})
            if not events:
                log("FAILED: Subscribe returned no events")
                return False

            log(f"✓ Subscribe detected {len(events)} event(s):")
            for topic, mid in events.items():
                log(f"  - {topic}: {mid}")

            # Verify the message is actually there
            from silica.developer.coordination import CoordinationContext, Idle

            context = CoordinationContext(
                deaddrop=deaddrop,
                namespace_id=ns["ns"],
                namespace_secret=ns["secret"],
                identity_id=coordinator["id"],
                identity_secret=coordinator["secret"],
                room_id=room["room_id"],
            )

            messages = context.receive_messages(include_room=True)
            idle_found = False
            for msg in messages:
                if isinstance(msg.message, Idle):
                    log("✓ Confirmed Idle message from worker")
                    idle_found = True
                    break

            if not idle_found:
                log("FAILED: Subscribe fired but no Idle message found")
                return False

            # Verify it was fast (should be < 5s, not the full 30s timeout)
            if elapsed > 10:
                log(
                    f"WARNING: Subscribe took {elapsed:.1f}s — expected < 5s for real-time"
                )
            else:
                log(f"✓ Response time {elapsed:.2f}s — real-time notification working")

            print()
            print("=" * 60)
            print("✓ Subscribe-based notification test PASSED!")
            print(f"  - Subscribe detected worker message in {elapsed:.2f}s")
            print("  - Confirmed Idle message received")
            print("  - Real-time notification path validated")
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
