#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts"]
# ///

"""Check for new iMessage messages since a given timestamp.

Efficient cursor-based check — uses the indexed date column to find only
new messages across all conversations. Returns messages grouped by contact
with resolved contact names from the macOS AddressBook.

Metadata:
    category: communication
    tags: imessage, messages, new, check
    creator_persona: twin
    created: 2026-02-20
    long_running: false
"""

import json
import sys
import sqlite3
import plistlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import cyclopts

sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema

app = cyclopts.App()

DEFAULT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"
APPLE_EPOCH = 978307200  # 2001-01-01 in unix seconds


def extract_message_text(text, attributed_body, message_summary_info):
    """Extract readable text from message columns."""
    if text:
        return text

    if attributed_body:
        try:
            ns_string_idx = attributed_body.find(b'NSString')
            if ns_string_idx == -1:
                return None
            content_marker = b'\x01+'
            text_start = attributed_body.find(content_marker, ns_string_idx)
            if text_start == -1:
                return None
            text_start += len(content_marker)
            while text_start < len(attributed_body) and attributed_body[text_start] < 0x20:
                text_start += 1
            text_end = attributed_body.find(b'\x86', text_start)
            if text_end == -1:
                text_end = len(attributed_body)
            text_data = attributed_body[text_start:text_end]
            decoded = text_data.decode('utf-8', errors='replace')
            cleaned = ''.join(char for char in decoded if char == '\n' or char >= ' ')
            cleaned = cleaned.replace('\ufffd', '').replace('\ufffc', '').strip()
            return cleaned if cleaned else None
        except Exception:
            pass

    if message_summary_info:
        try:
            plist = plistlib.loads(message_summary_info)
            if 'ec' in plist and '0' in plist['ec']:
                latest_edit = plist['ec']['0'][-1]
                if 't' in latest_edit:
                    return extract_message_text(None, latest_edit['t'], None)
        except Exception:
            pass

    return None


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
    since: Optional[str] = None,
    minutes: Optional[int] = None,
    *,
    toolspec: bool = False,
    authorize: bool = False,
):
    """Check for new iMessage messages since a timestamp or within N minutes.

    Uses indexed date column for efficient lookups. Returns messages grouped
    by contact with newest cursor timestamp for next poll.

    Args:
        since: UTC timestamp (ISO format, e.g. 2026-02-20T23:00:00Z). Messages after this time are returned.
        minutes: Alternative to since — get messages from last N minutes (default: 10).
    """
    if toolspec:
        print(json.dumps(generate_schema(main, "imessage_check_new")))
        return

    if authorize:
        print(json.dumps({"success": True, "message": "No authorization needed"}))
        return

    if not DEFAULT_DB_PATH.exists():
        print(json.dumps({"success": False, "error": f"Messages database not found at: {DEFAULT_DB_PATH}"}))
        return

    # Determine cutoff time
    now = datetime.now(timezone.utc)
    if since:
        try:
            cutoff = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except ValueError:
            print(json.dumps({"success": False, "error": f"Invalid timestamp format: {since}. Use ISO format like 2026-02-20T23:00:00Z"}))
            return
    else:
        cutoff = now - timedelta(minutes=minutes or 10)

    # Convert to Apple nanosecond timestamp
    apple_ns = int((cutoff.timestamp() - APPLE_EPOCH) * 1_000_000_000)

    try:
        db = sqlite3.connect(f"file:///{DEFAULT_DB_PATH}?mode=ro", uri=True)
        cursor = db.cursor()

        cursor.execute("""
            SELECT m.date, m.text, m.is_from_me, m.attributedBody,
                   m.message_summary_info, h.id as handle_id,
                   m.cache_has_attachments
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.date > ?
            ORDER BY m.date ASC
        """, (apple_ns,))

        rows = cursor.fetchall()

        # Group by contact
        contacts = {}
        latest_date = apple_ns
        unique_handles = set()
        for row in rows:
            date_ns, text, is_from_me, attr_body, summary_info, handle_id, has_attachments = row

            if date_ns > latest_date:
                latest_date = date_ns

            msg_text = extract_message_text(text, attr_body, summary_info)
            unix_ts = date_ns / 1_000_000_000 + APPLE_EPOCH
            msg_dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)

            contact = handle_id or ("me" if is_from_me else "unknown")
            if contact not in contacts:
                contacts[contact] = []
            if handle_id:
                unique_handles.add(handle_id)

            msg = {
                "text": msg_text,
                "date": msg_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "is_from_me": bool(is_from_me),
            }
            if has_attachments:
                msg["has_attachments"] = True
            contacts[contact].append(msg)

        # Build cursor for next poll
        cursor_ts = datetime.fromtimestamp(
            latest_date / 1_000_000_000 + APPLE_EPOCH, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        db.close()

        # Resolve contact names
        name_map = _resolve_contacts(list(unique_handles))

        result = {
            "new_messages": len(rows),
            "cursor": cursor_ts,
            "checked_since": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "contacts": {
                contact: {
                    "contact_name": name_map.get(contact),
                    "count": len(msgs),
                    "messages": msgs,
                }
                for contact, msgs in contacts.items()
            },
        }

        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))


if __name__ == "__main__":
    app()
