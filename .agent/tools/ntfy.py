#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts", "httpx"]
# ///

"""Send push notifications via ntfy.sh.

This tool sends push notifications to a configured ntfy.sh topic,
useful for urgent alerts or "check deaddrop" pings from Twin.

Metadata:
    category: notifications
    tags: ntfy, push, alerts
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

sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema

app = cyclopts.App()

# Config
CONFIG_PATH = Path.home() / ".config" / "twin" / "ntfy.json"
DEFAULT_CONFIG = {
    "topic": "twin-fudwdrpdekvr",
    "server": "https://ntfy.sh",
    "default_click": "https://deaddrop.dokku.heare.io/app"
}

def get_config() -> dict:
    """Load config or return defaults."""
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return DEFAULT_CONFIG.copy()


@app.default
def main(
    message: Optional[str] = None,
    title: Optional[str] = None,
    priority: int = 3,
    tags: Optional[str] = None,
    click: Optional[str] = None,
    *,
    toolspec: bool = False,
    authorize: bool = False,
):
    """Send push notifications via ntfy.sh for urgent alerts or deaddrop pings.

    Args:
        message: The notification message to send (required)
        title: Optional title for the notification
        priority: Priority 1-5 (1=min, 3=default, 5=urgent)
        tags: Comma-separated tags (emoji shortcodes: robot, warning, etc.)
        click: URL to open when notification is clicked (defaults to deaddrop)
    """
    if toolspec:
        schema = generate_schema(main, "ntfy")
        # Mark message as required in the schema
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

    config = get_config()
    topic = config["topic"]
    server = config["server"]
    default_click = config.get("default_click", "https://deaddrop.dokku.heare.io/app")
    
    headers = {
        "Priority": str(priority),
        "Click": click or default_click,  # Always include click URL
    }
    
    if title:
        headers["Title"] = title
    if tags:
        headers["Tags"] = tags
    
    url = f"{server}/{topic}"
    
    try:
        response = httpx.post(url, content=message.encode('utf-8'), headers=headers, timeout=10)
        
        if response.status_code == 200:
            result = {
                "success": True,
                "topic": topic,
                "priority": priority,
                "click": headers["Click"],
                "message": f"Notification sent to {topic}"
            }
        else:
            result = {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}"
            }
    except Exception as e:
        result = {
            "success": False,
            "error": str(e)
        }
    
    print(json.dumps(result))


if __name__ == "__main__":
    app()
