#!/usr/bin/env python3
"""Test connectivity to remote deaddrop server.

This script validates that:
1. We can connect to the remote deaddrop server
2. We can create a namespace
3. We can create identities
4. We can send and receive messages
5. We can create and use rooms

Run with: uv run python scripts/e2e/test_connectivity.py
"""

import sys
import time
from datetime import datetime

from config import get_e2e_deaddrop, test_namespace


def test_basic_connectivity():
    """Test basic connectivity to remote deaddrop."""
    print("=" * 60)
    print("E2E Test: Remote Deaddrop Connectivity")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    print(f"✓ Connected to: {deaddrop.location}")

    with test_namespace(deaddrop, prefix="connectivity-test") as ns:
        print(f"✓ Created namespace: {ns['ns']}")

        # Create two identities
        alice = deaddrop.create_identity(
            ns=ns["ns"],
            display_name="Alice",
            ns_secret=ns["secret"],
        )
        print(f"✓ Created identity: Alice ({alice['id'][:8]}...)")

        bob = deaddrop.create_identity(
            ns=ns["ns"],
            display_name="Bob",
            ns_secret=ns["secret"],
        )
        print(f"✓ Created identity: Bob ({bob['id'][:8]}...)")

        # Alice sends message to Bob
        msg_body = f"Hello from E2E test at {datetime.now().isoformat()}"
        result = deaddrop.send_message(
            ns=ns["ns"],
            from_secret=alice["secret"],
            to_id=bob["id"],
            body=msg_body,
            content_type="text/plain",
        )
        print(f"✓ Sent message: {result.get('mid', 'unknown')[:8]}...")

        # Bob receives message
        messages = deaddrop.get_inbox(
            ns=ns["ns"],
            identity_id=bob["id"],
            secret=bob["secret"],
        )
        assert len(messages) >= 1, f"Expected at least 1 message, got {len(messages)}"
        assert messages[0]["body"] == msg_body, "Message body mismatch"
        print("✓ Received message in inbox")

        # Test room (optional - may not be deployed)
        try:
            room = deaddrop.create_room(
                ns=ns["ns"],
                creator_secret=alice["secret"],
                display_name="Test Room",
            )
            print(f"✓ Created room: {room['room_id'][:8]}...")

            # Add Bob to room
            deaddrop.add_room_member(
                ns=ns["ns"],
                room_id=room["room_id"],
                identity_id=bob["id"],
                secret=alice["secret"],
            )
            print("✓ Added Bob to room")

            # Alice broadcasts to room
            room_msg = f"Room message at {datetime.now().isoformat()}"
            deaddrop.send_room_message(
                ns=ns["ns"],
                room_id=room["room_id"],
                secret=alice["secret"],
                body=room_msg,
                content_type="text/plain",
            )
            print("✓ Sent room message")

            # Bob receives room message
            room_messages = deaddrop.get_room_messages(
                ns=ns["ns"],
                room_id=room["room_id"],
                secret=bob["secret"],
            )
            assert (
                len(room_messages) >= 1
            ), f"Expected room message, got {len(room_messages)}"
            print("✓ Received room message")
        except RuntimeError as e:
            if "404" in str(e):
                print("⚠ Rooms not available on this server (skipping room tests)")
            else:
                raise

        print("✓ Namespace will be cleaned up")

    print()
    print("=" * 60)
    print("✓ All connectivity tests passed!")
    print("=" * 60)
    return True


def test_long_polling():
    """Test long-polling behavior."""
    print()
    print("=" * 60)
    print("E2E Test: Long Polling")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()

    with test_namespace(deaddrop, prefix="longpoll-test") as ns:
        # Create identity
        identity = deaddrop.create_identity(
            ns=ns["ns"],
            display_name="Poller",
            ns_secret=ns["secret"],
        )

        # Test that long-poll returns quickly when empty (should timeout)
        print("Testing 3-second long-poll on empty inbox...")
        start = time.time()
        messages = deaddrop.get_inbox(
            ns=ns["ns"],
            identity_id=identity["id"],
            secret=identity["secret"],
            wait=3,  # 3 second timeout
        )
        elapsed = time.time() - start
        print(f"✓ Long-poll returned in {elapsed:.2f}s with {len(messages)} messages")

        # Verify it actually waited (at least 2 seconds)
        if elapsed < 2:
            print(
                f"⚠ Warning: Long-poll returned faster than expected ({elapsed:.2f}s)"
            )
        else:
            print("✓ Long-poll timing looks correct")

    print()
    print("=" * 60)
    print("✓ Long polling test passed!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        test_basic_connectivity()
        test_long_polling()
        print()
        print("🎉 All E2E connectivity tests passed!")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
