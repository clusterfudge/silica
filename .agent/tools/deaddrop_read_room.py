#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts", "httpx", "pyyaml"]
# ///

"""Read messages from the Twin Chat room in Deaddrop.

Metadata:
    category: communication
    tags: deaddrop, chat, room, messaging
    creator_persona: twin
    created: 2026-02-12
    long_running: false
"""

import json
import sys
from pathlib import Path
from typing import Optional

import cyclopts
import httpx
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema

app = cyclopts.App()


def _load_config():
    config_path = Path(__file__).parent / "deaddrop_config.yaml"
    return yaml.safe_load(config_path.read_text())


def _get_secret(config):
    ns = config["namespace"]
    twin_id = config["twin_id"]
    creds_path = Path.home() / ".config/deadrop/namespaces" / f"{ns}.yaml"
    creds = yaml.safe_load(creds_path.read_text())
    return creds["mailboxes"][twin_id]["secret"]


@app.default
def main(
    limit: int = 10,
    after: Optional[str] = None,
    *,
    toolspec: bool = False,
    authorize: bool = False,
):
    """Read recent messages from the Twin Chat room.

    Args:
        limit: Number of messages to fetch (default 10)
        after: Only return messages after this message ID (cursor)
    """
    if toolspec:
        print(json.dumps(generate_schema(main, "deaddrop_read_room")))
        return

    if authorize:
        print(json.dumps({"success": True, "message": "No authorization needed"}))
        return

    try:
        config = _load_config()
        secret = _get_secret(config)
        url = f"{config['url']}/{config['namespace']}/rooms/{config['room_id']}/messages?limit={limit}"
        if after:
            url += f"&after={after}"

        resp = httpx.get(url, headers={"X-Inbox-Secret": secret}, timeout=30.0)
        resp.raise_for_status()

        data = resp.json()
        messages = data.get("messages", [])
        sean_id = config["sean_id"]

        formatted = []
        for msg in messages:
            sender = "Sean" if msg["from_id"] == sean_id else "Twin"
            formatted.append({
                "sender": sender,
                "from_id": msg["from_id"][:8],
                "body": msg["body"],
                "time": msg["created_at"][:19],
                "mid": msg["mid"],
            })

        print(json.dumps({"messages": formatted, "count": len(formatted)}))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))


if __name__ == "__main__":
    app()
