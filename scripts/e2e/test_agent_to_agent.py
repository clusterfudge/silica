#!/usr/bin/env python3
"""E2E Test: Agent-to-agent direct communication.

This test verifies:
1. Workers can list other workers in the session
2. Workers can send direct messages to each other
3. Workers can create collaboration rooms
4. Workers can invite others and send room messages

Run with: uv run python scripts/e2e/test_agent_to_agent.py
"""

import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from silica.developer.coordination.session import CoordinationSession


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def get_configured_deaddrop():
    from deadrop import Deaddrop
    from deadrop.config import GlobalConfig

    config = GlobalConfig.load()
    return Deaddrop.remote(url=config.url, bearer_token=config.bearer_token)


def main():
    print("=" * 60)
    print("E2E Test: Agent-to-Agent Communication")
    print("=" * 60)

    deaddrop = get_configured_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    # Create session
    log("Creating coordination session...")
    session = CoordinationSession.create_session(
        deaddrop=deaddrop,
        display_name="Agent-to-Agent Test",
    )
    log(f"✓ Session: {session.session_id}")

    # Create two worker identities manually (simulating spawned workers)
    log("Creating worker identities...")
    alice = deaddrop.create_identity(
        ns=session.namespace_id,
        display_name="Alice",
        ns_secret=session.namespace_secret,
    )
    bob = deaddrop.create_identity(
        ns=session.namespace_id,
        display_name="Bob",
        ns_secret=session.namespace_secret,
    )
    log(f"✓ Alice: {alice['id'][:12]}...")
    log(f"✓ Bob: {bob['id'][:12]}...")

    # Add both to coordination room
    log("Adding workers to coordination room...")
    deaddrop.add_room_member(
        ns=session.namespace_id,
        room_id=session.state.room_id,
        identity_id=alice["id"],
        secret=session.state.coordinator_secret,
    )
    deaddrop.add_room_member(
        ns=session.namespace_id,
        room_id=session.state.room_id,
        identity_id=bob["id"],
        secret=session.state.coordinator_secret,
    )
    log("✓ Workers added to room")

    # Test 1: List workers (from Alice's perspective)
    log("\n--- Test 1: List Workers ---")
    room_members = deaddrop.list_room_members(
        ns=session.namespace_id,
        room_id=session.state.room_id,
        secret=alice["secret"],
    )
    log(f"Alice sees {len(room_members)} participants in room")
    for member in room_members:
        log(
            f"  - {member.get('display_name', 'N/A')} ({member.get('identity_id', 'N/A')[:8]}...)"
        )

    if len(room_members) < 2:
        log("FAILED: Expected at least 2 members")
        return False
    log("✓ Workers can list room members")

    # Test 2: Direct message from Alice to Bob
    log("\n--- Test 2: Direct Message ---")
    log("Alice sending direct message to Bob...")
    deaddrop.send_message(
        ns=session.namespace_id,
        to_id=bob["id"],
        body=json.dumps(
            {
                "type": "text",
                "from_agent": "alice-agent",
                "content": "Hello Bob! This is a direct message from Alice.",
            }
        ),
        from_secret=alice["secret"],
        content_type="application/vnd.silica.worker-message+json",
    )
    log("✓ Message sent")

    # Bob checks inbox
    log("Bob checking inbox...")
    bob_inbox = deaddrop.get_inbox(
        ns=session.namespace_id,
        identity_id=bob["id"],
        secret=bob["secret"],
    )
    log(f"Bob has {len(bob_inbox)} messages")

    if len(bob_inbox) == 0:
        log("FAILED: Bob should have received a message")
        return False

    # Parse and verify message
    msg = bob_inbox[0]
    content = json.loads(msg["body"])
    log(f"  From: {content.get('from_agent')}")
    log(f"  Content: {content.get('content')}")
    log("✓ Direct message received")

    # Test 3: Alice creates a collaboration room
    log("\n--- Test 3: Create Collaboration Room ---")
    log("Alice creating collaboration room...")
    collab_room = deaddrop.create_room(
        ns=session.namespace_id,
        creator_secret=alice["secret"],
        display_name="Alice-Bob Collab",
    )
    collab_room_id = collab_room["room_id"]
    log(f"✓ Room created: {collab_room_id[:12]}...")

    # Test 4: Alice invites Bob to the room
    log("\n--- Test 4: Invite to Room ---")
    log("Alice inviting Bob to collaboration room...")
    deaddrop.add_room_member(
        ns=session.namespace_id,
        room_id=collab_room_id,
        identity_id=bob["id"],
        secret=alice["secret"],
    )
    log("✓ Bob invited")

    # Verify Bob is in the room
    bob_rooms = deaddrop.list_rooms(
        ns=session.namespace_id,
        secret=bob["secret"],
    )
    collab_rooms = [r for r in bob_rooms if r.get("room_id") == collab_room_id]
    if not collab_rooms:
        log("FAILED: Bob should be in the collaboration room")
        return False
    log("✓ Bob is now a member of collaboration room")

    # Test 5: Send message to collaboration room
    log("\n--- Test 5: Room Message ---")
    log("Alice sending message to collaboration room...")
    deaddrop.send_room_message(
        ns=session.namespace_id,
        room_id=collab_room_id,
        body=json.dumps(
            {
                "type": "text",
                "from_agent": "alice-agent",
                "content": "Let's collaborate on this sub-task!",
            }
        ),
        secret=alice["secret"],
        content_type="application/vnd.silica.worker-message+json",
    )
    log("✓ Room message sent")

    # Bob reads room messages
    log("Bob reading collaboration room messages...")
    room_msgs = deaddrop.get_room_messages(
        ns=session.namespace_id,
        room_id=collab_room_id,
        secret=bob["secret"],
    )
    log(f"Room has {len(room_msgs)} messages")

    if len(room_msgs) == 0:
        log("FAILED: Room should have messages")
        return False

    for msg in room_msgs:
        content = json.loads(msg["body"])
        log(f"  From: {content.get('from_agent')}")
        log(f"  Content: {content.get('content')}")
    log("✓ Room messages readable by members")

    # Test 6: Bob replies in the room
    log("\n--- Test 6: Bob Replies ---")
    log("Bob sending reply to collaboration room...")
    deaddrop.send_room_message(
        ns=session.namespace_id,
        room_id=collab_room_id,
        body=json.dumps(
            {
                "type": "text",
                "from_agent": "bob-agent",
                "content": "Got it! I'll work on my part.",
            }
        ),
        secret=bob["secret"],
    )
    log("✓ Bob's reply sent")

    # Alice reads updated room
    room_msgs = deaddrop.get_room_messages(
        ns=session.namespace_id,
        room_id=collab_room_id,
        secret=alice["secret"],
    )
    log(f"Collaboration room now has {len(room_msgs)} messages")

    if len(room_msgs) < 2:
        log("FAILED: Room should have both messages")
        return False
    log("✓ Bi-directional room communication works")

    print()
    print("=" * 60)
    print("✓ Agent-to-Agent Communication Test PASSED!")
    print("=" * 60)
    print("Verified:")
    print("  1. Workers can list other workers in the room")
    print("  2. Workers can send direct messages to each other")
    print("  3. Workers can create collaboration rooms")
    print("  4. Workers can invite others to rooms")
    print("  5. Workers can send and receive room messages")
    print("  6. Bi-directional communication works")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
