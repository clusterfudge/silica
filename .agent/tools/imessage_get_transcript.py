#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts", "imessagedb", "phonenumbers"]
# ///

"""Get iMessage chat transcript for phone numbers or emails.

Resolves contact names from the macOS AddressBook and includes them
in the response alongside raw identifiers.

Metadata:
    category: communication
    tags: imessage, messages, transcript, chat
    creator_persona: twin
    created: 2026-02-12
    long_running: false
"""

import json
import sys
import contextlib
import io
import plistlib
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cyclopts
import imessagedb
import phonenumbers

sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema

app = cyclopts.App()

DEFAULT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"


def convert_heic_to_jpeg(input_heic: Path, output_jpeg: Path) -> bool:
    try:
        if not input_heic.exists():
            return False
        subprocess.run(
            ["magick", "convert", str(input_heic), str(output_jpeg)],
            check=True, capture_output=True, text=True,
        )
        return True
    except Exception:
        return False


def extract_message_text(text, attributed_body, message_summary_info):
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


def copy_and_convert_attachment(attachment_path: Path, destination_dir: Path):
    if not attachment_path.exists():
        return None
    destination_dir.mkdir(parents=True, exist_ok=True)
    if attachment_path.suffix.lower() == '.heic':
        dest_path = destination_dir / (attachment_path.stem + '.jpeg')
        if convert_heic_to_jpeg(attachment_path, dest_path):
            return dest_path
        return None
    else:
        dest_path = destination_dir / attachment_path.name
        shutil.copy2(attachment_path, dest_path)
        return dest_path


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
    identifiers: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    *,
    toolspec: bool = False,
    authorize: bool = False,
):
    """Get chat transcript for one or more identifiers (phone numbers/emails) within a date range.

    Args:
        identifiers: Comma-separated list of identifiers (phone numbers in E.164 format preferred, or email addresses)
        start_date: Optional start date in ISO format (YYYY-MM-DD)
        end_date: Optional end date in ISO format (YYYY-MM-DD)
    """
    if toolspec:
        schema = generate_schema(main, "imessage_get_transcript")
        if "identifiers" not in schema.get("input_schema", {}).get("required", []):
            schema.setdefault("input_schema", {}).setdefault("required", []).append("identifiers")
        print(json.dumps(schema))
        return

    if authorize:
        print(json.dumps({"success": True, "message": "No authorization needed"}))
        return

    if not identifiers:
        print(json.dumps({"success": False, "error": "identifiers is required"}))
        return

    # Normalize "null" strings
    if start_date in ("null", ""):
        start_date = None
    if end_date in ("null", ""):
        end_date = None

    if not DEFAULT_DB_PATH.exists():
        print(json.dumps({"success": False, "error": f"Messages database not found at: {DEFAULT_DB_PATH}"}))
        return

    # Parse identifiers
    id_list = [i.strip() for i in identifiers.split(',')]
    normalized_ids = []
    for identifier in id_list:
        if '@' in identifier:
            normalized_ids.append(identifier)
        else:
            try:
                parsed = phonenumbers.parse(identifier, "US")
                if not phonenumbers.is_valid_number(parsed):
                    print(json.dumps({"success": False, "error": f"Invalid phone number: {identifier}"}))
                    return
                normalized_ids.append(phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164))
            except phonenumbers.NumberParseException as e:
                print(json.dumps({"success": False, "error": f"Invalid phone number format for {identifier}: {e}"}))
                return

    if not normalized_ids:
        print(json.dumps({"success": False, "error": "No valid identifiers provided"}))
        return

    # Resolve contact names for the requested identifiers
    name_map = _resolve_contacts(normalized_ids)

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            db = imessagedb.DB(str(DEFAULT_DB_PATH))

            # Check which identifiers exist
            valid_ids = []
            invalid_ids = []
            for identifier in normalized_ids:
                db.connection.execute("SELECT COUNT(*) FROM handle WHERE id = ?", (identifier,))
                if db.connection.fetchone()[0] == 0:
                    invalid_ids.append(identifier)
                else:
                    valid_ids.append(identifier)

            if not valid_ids:
                print(json.dumps({
                    "messages": [], "total_count": 0,
                    "warnings": [f"None of the provided identifiers found: {', '.join(invalid_ids)}"],
                }))
                return

            placeholders = ','.join(['?' for _ in valid_ids])
            query = f"""
                SELECT DISTINCT m1.ROWID, m1.guid, m1.text, m1.is_from_me, m1.date,
                       m1.attributedBody, m1.message_summary_info, m1.handle_id
                FROM message m1
                WHERE m1.handle_id IN (SELECT rowid FROM handle WHERE id IN ({placeholders}))
                UNION
                SELECT DISTINCT m2.ROWID, m2.guid, m2.text, m2.is_from_me, m2.date,
                       m2.attributedBody, m2.message_summary_info, m2.handle_id
                FROM message m2
                JOIN chat_message_join cmj ON m2.ROWID = cmj.message_id
                JOIN chat c ON cmj.chat_id = c.ROWID
                JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
                WHERE chj.handle_id IN (SELECT rowid FROM handle WHERE id IN ({placeholders}))
                ORDER BY date ASC
            """
            db.connection.execute(query, valid_ids + valid_ids)
            rows = db.connection.fetchall()

            # Build a handle_id (ROWID) -> identifier mapping
            handle_rowid_to_id = {}
            for vid in valid_ids:
                db.connection.execute("SELECT rowid FROM handle WHERE id = ?", (vid,))
                for (rid,) in db.connection.fetchall():
                    handle_rowid_to_id[rid] = vid

            filtered_messages = []
            downloads_dir = Path.home() / "Downloads"

            for row in rows:
                rowid, guid, text, is_from_me, date, attributed_body, message_summary_info, handle_id = row
                msg_dt = datetime.fromtimestamp(date / 1000000000 + 978307200).astimezone(timezone.utc)
                msg_date = msg_dt.date()

                if start_date:
                    if msg_date < datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc).date():
                        continue
                if end_date:
                    if msg_date > datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc).date():
                        continue

                message_text = extract_message_text(text, attributed_body, message_summary_info)

                attachments = []
                if rowid in db.attachment_list.message_join:
                    for att in db.attachment_list.message_join[rowid]:
                        if att in db.attachment_list.attachment_list:
                            attachment = db.attachment_list.attachment_list[att]
                            if not attachment.missing:
                                try:
                                    src_path = Path(attachment.original_path)
                                    new_path = copy_and_convert_attachment(src_path, downloads_dir)
                                    if new_path:
                                        attachments.append({
                                            'path': str(new_path),
                                            'mime_type': 'image/jpeg' if src_path.suffix.lower() == '.heic' else attachment.mime_type,
                                        })
                                except Exception:
                                    pass

                # Resolve sender
                sender_handle = handle_rowid_to_id.get(handle_id)
                sender_name = name_map.get(sender_handle) if sender_handle else None

                msg = {
                    "text": message_text,
                    "date": msg_dt.strftime("%Y-%m-%d %H:%M:%SZ"),
                    "is_from_me": bool(is_from_me),
                    "has_attachments": bool(attachments),
                    "attachments": attachments,
                }
                if not is_from_me and sender_name:
                    msg["sender_name"] = sender_name

                filtered_messages.append(msg)

            response = {
                "messages": filtered_messages,
                "total_count": len(filtered_messages),
                "participants": {
                    vid: name_map.get(vid) or vid for vid in valid_ids
                },
            }
            if invalid_ids:
                response["warnings"] = [f"Not found in database: {', '.join(invalid_ids)}"]

        print(json.dumps(response))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))


if __name__ == "__main__":
    app()
