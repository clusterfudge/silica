#!/usr/bin/env python3
"""Debug script to analyze the problematic session."""

import json
import sys
from pathlib import Path

# Add the silica source to path
sys.path.insert(0, str(Path(__file__).parent))

from silica.developer.compaction_validation import (
    strip_orphaned_tool_blocks,
    validate_message_structure,
)


def analyze_messages(messages, label=""):
    """Analyze tool_use/tool_result pairing in messages."""
    print(f"\n{'='*60}")
    print(f"Analyzing: {label}")
    print(f"Total messages: {len(messages)}")
    print(f"{'='*60}")

    tool_uses = {}  # id -> (msg_idx, name)
    tool_results = {}  # tool_use_id -> msg_idx

    for idx, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content", [])

        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_use":
                        tool_id = block.get("id", "")
                        tool_name = block.get("name", "unknown")
                        tool_uses[tool_id] = (idx, tool_name)
                        print(
                            f"  msg {idx} ({role}): tool_use id={tool_id[:30]}... name={tool_name}"
                        )
                    elif block.get("type") == "tool_result":
                        tool_use_id = block.get("tool_use_id", "")
                        tool_results[tool_use_id] = idx
                        print(
                            f"  msg {idx} ({role}): tool_result for={tool_use_id[:30]}..."
                        )

    print(f"\nTotal tool_uses: {len(tool_uses)}")
    print(f"Total tool_results: {len(tool_results)}")

    # Find orphans
    use_ids = set(tool_uses.keys())
    result_ids = set(tool_results.keys())

    orphan_uses = use_ids - result_ids
    orphan_results = result_ids - use_ids

    if orphan_uses:
        print("\nOrphan tool_uses (no result):")
        for tid in orphan_uses:
            idx, name = tool_uses[tid]
            print(f"  msg {idx}: {name} - {tid}")

    if orphan_results:
        print("\nOrphan tool_results (no use):")
        for tid in orphan_results:
            idx = tool_results[tid]
            print(f"  msg {idx}: {tid}")

    # Validate
    report = validate_message_structure(messages)
    print(f"\nValidation: {'VALID' if report.is_valid else 'INVALID'}")
    if not report.is_valid:
        for issue in report.issues:
            if issue.level.value == "ERROR":
                print(f"  ERROR: {issue.message}")

    return orphan_uses, orphan_results


def main():
    # Load the session
    session_path = (
        Path.home()
        / ".silica/personas/autonomous_engineer/history/28b202e6-82e3-49f5-b324-78da20b43ff1/root.json"
    )

    if not session_path.exists():
        print(f"Session not found: {session_path}")
        return 1

    with open(session_path) as f:
        data = json.load(f)

    messages = data["messages"]

    # Analyze current state
    analyze_messages(messages, "Current session state")

    # Simulate user typing "continue"
    messages_with_continue = messages + [
        {"role": "user", "content": [{"type": "text", "text": "continue"}]}
    ]
    analyze_messages(messages_with_continue, "After user types 'continue'")

    # Run cleanup
    cleaned = strip_orphaned_tool_blocks(messages_with_continue)
    analyze_messages(cleaned, "After cleanup")

    # Simulate assistant response with tool_use
    new_tool_id = "toolu_TEST_NEW_TOOL_ID_12345"
    cleaned.append(
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I'll help with that."},
                {
                    "type": "tool_use",
                    "id": new_tool_id,
                    "name": "edit_file",
                    "input": {"path": "test.py"},
                },
            ],
        }
    )
    analyze_messages(cleaned, "After assistant responds with tool_use")

    # Simulate tool result being added
    cleaned.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": new_tool_id,
                    "content": "File edited successfully",
                }
            ],
        }
    )
    analyze_messages(cleaned, "After tool_result added")

    # Run cleanup again (this is what happens before the second API call)
    cleaned2 = strip_orphaned_tool_blocks(cleaned)
    analyze_messages(cleaned2, "After second cleanup")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Original: {len(messages)} messages")
    print(f"After continue: {len(messages_with_continue)} messages")
    print(
        f"After cleanup 1: {len(cleaned) - 2} messages (before adding new assistant/user)"
    )
    print(f"After assistant+result: {len(cleaned)} messages")
    print(f"After cleanup 2: {len(cleaned2)} messages")

    return 0


if __name__ == "__main__":
    sys.exit(main())
