#!/usr/bin/env python3
"""
CLI tools for managing developer sessions.
Provides functionality to list and resume previous developer sessions.
These functions can be used both as CLI tools and as agent tools.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich import box

# Default history directory location
DEFAULT_HISTORY_DIR = Path.home() / ".hdev" / "history"


def get_history_dir() -> Path:
    """Get the path to the history directory."""
    return DEFAULT_HISTORY_DIR


def list_sessions(workdir: Optional[str] = None) -> List[Dict]:
    """
    List available developer sessions with metadata.

    Args:
        workdir: Optional working directory to filter sessions by.
                If provided, only sessions from this directory will be listed.

    Returns:
        List of session data dictionaries.
    """
    history_dir = get_history_dir()

    if not history_dir.exists():
        return []

    sessions = []

    for session_dir in history_dir.iterdir():
        if not session_dir.is_dir():
            continue

        root_file = session_dir / "root.json"
        if not root_file.exists():
            continue

        try:
            with open(root_file, "r") as f:
                session_data = json.load(f)

            # Skip if no metadata (pre-HDEV-58 sessions)
            if "metadata" not in session_data:
                continue

            metadata = session_data["metadata"]

            # Filter by root directory if workdir is specified
            if workdir:
                # Normalize paths for comparison
                session_root = os.path.normpath(metadata.get("root_dir", ""))
                workdir_norm = os.path.normpath(workdir)

                if session_root != workdir_norm:
                    continue

            # Extract relevant information
            session_info = {
                "session_id": session_data.get("session_id", session_dir.name),
                "created_at": metadata.get("created_at"),
                "last_updated": metadata.get("last_updated"),
                "root_dir": metadata.get("root_dir"),
                "message_count": len(session_data.get("messages", [])),
                "model": session_data.get("model_spec", {}).get("title", "Unknown"),
            }

            sessions.append(session_info)

        except (json.JSONDecodeError, IOError, KeyError):
            # Skip invalid files
            continue

    # Sort by last_updated (newest first)
    sessions.sort(key=lambda x: x.get("last_updated", ""), reverse=True)

    return sessions


def get_session_data(session_id: str) -> Optional[Dict]:
    """
    Get data for a specific session.

    Args:
        session_id: ID or prefix of the session to retrieve.

    Returns:
        Session data dictionary if found, None otherwise.
    """
    history_dir = get_history_dir()

    # Find matching session directory
    matching_ids = [
        d.name
        for d in history_dir.iterdir()
        if d.is_dir() and d.name.startswith(session_id)
    ]

    if not matching_ids:
        return None

    session_dir = history_dir / matching_ids[0]
    root_file = session_dir / "root.json"

    if not root_file.exists():
        return None

    try:
        with open(root_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def print_session_list(sessions: List[Dict]) -> None:
    """
    Print a formatted list of sessions.

    Args:
        sessions: List of session data dictionaries.
    """
    console = Console()

    if not sessions:
        console.print("No sessions found with metadata.", style="yellow")
        return

    table = Table(title="Developer Sessions", box=box.ROUNDED)
    table.add_column("ID", style="cyan")
    table.add_column("Created", style="green")
    table.add_column("Last Updated", style="blue")
    table.add_column("Messages", style="magenta")
    table.add_column("Model", style="yellow")
    table.add_column("Root Directory", style="bright_black")

    for session in sessions:
        # Parse and format dates
        created = parse_iso_date(session.get("created_at", ""))
        updated = parse_iso_date(session.get("last_updated", ""))

        # Format session ID (use first 8 chars)
        short_id = session.get("session_id", "")[:8]

        # Add row to table
        table.add_row(
            short_id,
            created,
            updated,
            str(session.get("message_count", 0)),
            session.get("model", "Unknown"),
            session.get("root_dir", "Unknown"),
        )

    # Print table without any explicit syntax highlighting (will rely on markdown)
    console.print(table)


def parse_iso_date(date_string: str) -> str:
    """Parse ISO format date and return a human-readable string."""
    if not date_string:
        return "Unknown"

    try:
        dt = datetime.fromisoformat(date_string.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return date_string


# Tool function schemas for integration with agent tools
def list_sessions_tool(context: Any, **kwargs) -> str:
    """
    List available developer sessions.

    This tool lists all sessions with metadata, showing their ID,
    creation date, update date, message count, and working directory.
    """
    workdir = kwargs.get("workdir", None)
    sessions = list_sessions(workdir)

    if not sessions:
        return "No sessions found with metadata."

    result = "## Available Sessions\n\n"
    result += "| ID | Created | Last Updated | Messages | Working Directory |\n"
    result += "|---|---|---|---|---|\n"

    for session in sessions:
        # Parse and format dates
        created = parse_iso_date(session.get("created_at", ""))
        updated = parse_iso_date(session.get("last_updated", ""))

        # Format session ID (use first 8 chars)
        short_id = session.get("session_id", "")[:8]

        # Add row to table
        result += f"| {short_id} | {created} | {updated} | {session.get('message_count', 0)} | {session.get('root_dir', 'Unknown')} |\n"

    return result


def get_session_tool(context: Any, **kwargs) -> str:
    """
    Get details about a specific session.

    This tool retrieves detailed information about a session by its ID.
    """
    session_id = kwargs.get("session_id", "")
    if not session_id:
        return "Error: No session ID provided."

    session_data = get_session_data(session_id)
    if not session_data:
        return f"Session with ID '{session_id}' not found."

    metadata = session_data.get("metadata", {})

    result = f"## Session Details: {session_id}\n\n"
    result += f"- **Created**: {parse_iso_date(metadata.get('created_at', ''))}\n"
    result += (
        f"- **Last Updated**: {parse_iso_date(metadata.get('last_updated', ''))}\n"
    )
    result += f"- **Working Directory**: {metadata.get('root_dir', 'Unknown')}\n"
    result += f"- **Message Count**: {len(session_data.get('messages', []))}\n"
    result += (
        f"- **Model**: {session_data.get('model_spec', {}).get('title', 'Unknown')}\n"
    )

    return result


def resume_session(session_id: str) -> bool:
    """
    Resume a previous developer session.

    Args:
        session_id: ID or prefix of the session to resume.

    Returns:
        True if successful, False otherwise.
    """
    # Get basic session data to check metadata and root directory
    session_data = get_session_data(session_id)

    if not session_data or "metadata" not in session_data:
        console = Console()
        console.print(f"Session {session_id} not found or lacks metadata.", style="red")
        return False

    # Get the root directory from metadata
    root_dir = session_data.get("metadata", {}).get("root_dir")
    if not root_dir or not os.path.exists(root_dir):
        console = Console()
        console.print(
            f"Root directory '{root_dir}' not found for session {session_id}.",
            style="red",
        )
        return False

    # Get the stored CLI arguments
    metadata = session_data.get("metadata", {})
    stored_cli_args = metadata.get("cli_args")

    # Get the model name (fallback for compatibility)
    model = session_data.get("model_spec", {}).get("title", "sonnet-3.7")

    try:
        # Change to the root directory
        os.chdir(root_dir)

        # Construct hdev command
        history_dir = get_history_dir()
        full_session_id = None

        # Find matching session directory
        matching_ids = [
            d.name
            for d in history_dir.iterdir()
            if d.is_dir() and d.name.startswith(session_id)
        ]

        if matching_ids:
            full_session_id = matching_ids[0]
        else:
            return False

        console = Console()
        console.print(
            f"Resuming session {full_session_id} in {root_dir}", style="green"
        )

        # Reconstruct the hdev command from stored CLI arguments
        if stored_cli_args:
            # CLI args should be stored as a list
            if isinstance(stored_cli_args, list):
                hdev_command = _reconstruct_command_from_list(stored_cli_args)
            else:
                # Fallback to basic command for unexpected format
                console.print(
                    f"Unexpected CLI args format, using basic command with model: {model}",
                    style="yellow",
                )
                hdev_command = ["hdev", "--model", model]
        else:
            # Fallback for sessions without stored CLI args (backward compatibility)
            console.print(
                f"No stored CLI args found, using basic command with model: {model}",
                style="yellow",
            )
            hdev_command = ["hdev", "--model", model]

        # Launch hdev with environment variable to resume the session
        os.environ["HEARE_DEVELOPER_SESSION_ID"] = full_session_id

        console.print(f"Executing: {' '.join(hdev_command)}", style="blue")

        # Execute command (replace current process)
        os.execvp("hdev", hdev_command)

        return True
    except Exception as e:
        console = Console()
        console.print(f"Error resuming session: {e}", style="red")
        return False


def _reconstruct_command_from_list(original_args: list[str]) -> list[str]:
    """
    Reconstruct hdev command from original argument list, filtering out inappropriate args.

    Args:
        original_args: Original command line arguments

    Returns:
        List of command line arguments
    """
    command = ["hdev"]

    # Skip the first argument (program name) and filter out inappropriate arguments
    i = 1
    while i < len(original_args):
        arg = original_args[i]

        # Skip session-specific arguments that shouldn't be preserved
        if arg in ["--session-id", "--prompt"]:
            i += 2  # Skip both the flag and its value
            continue

        # Add the argument
        command.append(arg)

        # Check if this argument expects a value and add it too
        if arg in ["--model", "--summary-cache", "--sandbox-mode", "--persona"]:
            i += 1  # Move to the value
            if i < len(original_args):
                command.append(original_args[i])  # Add the value

        i += 1

    return command


# Tool schemas for integration with toolbox
def schema_list_sessions():
    """Schema for list_sessions_tool function."""
    return {
        "name": "list_sessions_tool",
        "description": "List available developer sessions with metadata.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workdir": {
                    "type": "string",
                    "description": "Optional working directory to filter sessions by. If provided, only sessions from this directory will be listed.",
                }
            },
            "required": [],
        },
    }


def schema_get_session():
    """Schema for get_session_tool function."""
    return {
        "name": "get_session_tool",
        "description": "Get details about a specific developer session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "ID or prefix of the session to retrieve details for.",
                }
            },
            "required": ["session_id"],
        },
    }


# Set schema methods on tool functions
list_sessions_tool.schema = schema_list_sessions
get_session_tool.schema = schema_get_session
