#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts", "imessagedb"]
# ///

"""List all iMessage conversations with resolved contact names.

Metadata:
    category: communication
    tags: imessage, messages, conversations
    creator_persona: twin
    created: 2026-02-12
    long_running: false
"""

import json
import re
import sys
import contextlib
import io
from pathlib import Path

import cyclopts
import imessagedb

sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema

app = cyclopts.App()

DEFAULT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"


def _resolve_contacts(handles):
    """Resolve handles to contact names. Returns dict of handle -> name."""
    try:
        from _contacts_resolver import ContactsResolver
        resolver = ContactsResolver()
        return resolver.resolve_handles_batch(handles)
    except Exception:
        return {}


@app.default
def main(
    *,
    toolspec: bool = False,
    authorize: bool = False,
):
    """List all conversations in the Messages database.

    Returns conversation list with participant info and last message dates.
    """
    if toolspec:
        print(json.dumps(generate_schema(main, "imessage_list_conversations")))
        return

    if authorize:
        print(json.dumps({"success": True, "message": "No authorization needed"}))
        return

    if not DEFAULT_DB_PATH.exists():
        print(json.dumps({"success": False, "error": f"Messages database not found at: {DEFAULT_DB_PATH}"}))
        return

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            db = imessagedb.DB(str(DEFAULT_DB_PATH))
            conversations_raw = db.chats.get_chats()

        conversation_list = [c for c in conversations_raw.split('\n') if c.strip()]

        # Extract phone numbers / emails from conversation lines for resolution
        handle_pattern = re.compile(r'(\+\d[\d\-]+\d|\S+@\S+\.\S+)')
        all_handles = set()
        for conv in conversation_list:
            for match in handle_pattern.findall(conv):
                all_handles.add(match)

        # Resolve all handles to names
        name_map = _resolve_contacts(list(all_handles)) if all_handles else {}

        # Enrich conversation lines with resolved names
        enriched = []
        for conv in conversation_list:
            handles_in_line = handle_pattern.findall(conv)
            resolved_names = []
            for h in handles_in_line:
                name = name_map.get(h)
                if name:
                    resolved_names.append(name)

            entry = {"raw": conv}
            if resolved_names:
                entry["resolved_names"] = resolved_names
            enriched.append(entry)

        print(json.dumps({
            "conversations": enriched,
            "total_count": len(enriched),
        }))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))


if __name__ == "__main__":
    app()
