#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts", "httpx", "pyyaml"]
# ///

"""Send a message to the Twin Chat room in Deaddrop.

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
    message: Optional[str] = None,
    content_type: str = "text/markdown",
    *,
    toolspec: bool = False,
    authorize: bool = False,
):
    """Send a message to the Twin Chat room.

    Args:
        message: The message text to send to the room
        content_type: MIME type of the message (default: text/markdown)
    """
    if toolspec:
        schema = generate_schema(main, "deaddrop_send_room")
        if "message" not in schema.get("input_schema", {}).get("required", []):
            schema.setdefault("input_schema", {}).setdefault("required", []).append("message")
        print(json.dumps(schema))
        return

    if authorize:
        print(json.dumps({"success": True, "message": "No authorization needed"}))
        return

    if not message:
        print(json.dumps({"success": False, "error": "message is required"}))
        return

    try:
        config = _load_config()
        secret = _get_secret(config)
        url = f"{config['url']}/{config['namespace']}/rooms/{config['room_id']}/messages"

        resp = httpx.post(
            url,
            json={"body": message, "content_type": content_type},
            headers={"X-Inbox-Secret": secret},
            timeout=30.0,
        )
        resp.raise_for_status()

        data = resp.json()
        print(json.dumps({"success": True, "mid": data.get("mid")}))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))


if __name__ == "__main__":
    app()
