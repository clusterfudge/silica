#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts"]
# ///

"""Search macOS Contacts by name, phone number, email, or organization.

Queries the AddressBook SQLite databases directly for fast lookups.

Metadata:
    category: communication
    tags: contacts, search, addressbook
    creator_persona: twin
    created: 2026-03-01
    long_running: false
"""

import json
import sys
from pathlib import Path
from typing import Optional

import cyclopts

sys.path.insert(0, str(Path(__file__).parent))
from _contacts_resolver import ContactsResolver
from _silica_toolspec import generate_schema

app = cyclopts.App()


@app.default
def main(
    query: Optional[str] = None,
    limit: int = 20,
    *,
    toolspec: bool = False,
    authorize: bool = False,
):
    """Search for contacts by name, phone number, email, or organization.

    Args:
        query: Search term (name, phone number, email, or organization). Case-insensitive.
        limit: Maximum number of results to return (default: 20)
    """
    if toolspec:
        schema = generate_schema(main, "contacts_search")
        if "query" not in schema.get("input_schema", {}).get("required", []):
            schema.setdefault("input_schema", {}).setdefault("required", []).append("query")
        print(json.dumps(schema))
        return

    if authorize:
        print(json.dumps({"success": True, "message": "No authorization needed"}))
        return

    if not query:
        print(json.dumps({"success": False, "error": "query is required"}))
        return

    try:
        resolver = ContactsResolver()
        results = resolver.search(query, limit=limit)

        print(json.dumps({
            "results": [c.to_dict() for c in results],
            "count": len(results),
            "query": query,
        }))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))


if __name__ == "__main__":
    app()
