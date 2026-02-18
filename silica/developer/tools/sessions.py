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

# Default history base directory location
DEFAULT_HISTORY_BASE_DIR = Path.home() / ".silica" / "personas" / "default"


def get_history_dir(history_base_dir: Optional[Path] = None) -> Path:
    """Get the path to the history directory.

    Args:
        history_base_dir: Base directory for history. If None, defaults to ~/.silica/personas/default

    Returns:
        Path to the history directory (base_dir/history)
    """
    base = history_base_dir if history_base_dir else DEFAULT_HISTORY_BASE_DIR
    return base / "history"


def _extract_first_user_message(messages: List[Dict]) -> Optional[str]:
    """Extract the text content of the first user message.

    Args:
        messages: List of message dictionaries

    Returns:
        The text content of the first user message, or None if not found
    """
    for message in messages:
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                # Handle structured content (list of content blocks)
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
            break
    return None


def _truncate_message(message: Optional[str], max_length: int = 60) -> str:
    """Truncate a message to a maximum length with ellipsis.

    Args:
        message: The message to truncate
        max_length: Maximum length including ellipsis

    Returns:
        Truncated message with ellipsis if needed
    """
    if not message:
        return ""

    # Clean up whitespace and newlines
    message = " ".join(message.split())

    if len(message) <= max_length:
        return message

    return message[: max_length - 3] + "..."


def _read_session_info(session_dir: Path) -> Optional[Dict]:
    """Read session info from v2 format or legacy root.json.

    Returns:
        Session info dict, or None if the session can't be read.
    """
    session_json = session_dir / "session.json"

    # Try v2 format first
    if session_json.exists():
        try:
            meta = json.loads(session_json.read_text())
            if meta.get("version", 0) >= 2:
                # Read context for message count and first message
                from silica.developer.session_store import SessionStore

                store = SessionStore(session_dir, agent_name="root")
                context_msgs = store.read_context()
                first_message = _extract_first_user_message(context_msgs)

                return {
                    "session_id": meta.get("session_id", session_dir.name),
                    "created_at": meta.get("created_at"),
                    "last_updated": meta.get("last_updated"),
                    "root_dir": meta.get("root_dir"),
                    "message_count": len(context_msgs),
                    "model": meta.get("model_spec", {}).get("title", "Unknown"),
                    "first_message": first_message,
                }
        except (json.JSONDecodeError, IOError):
            pass

    # Fall back to legacy root.json
    root_file = session_dir / "root.json"
    if not root_file.exists():
        return None

    with open(root_file, "r") as f:
        session_data = json.load(f)

    if "metadata" not in session_data:
        return None

    metadata = session_data["metadata"]
    messages = session_data.get("messages", [])
    first_message = _extract_first_user_message(messages)

    return {
        "session_id": session_data.get("session_id", session_dir.name),
        "created_at": metadata.get("created_at"),
        "last_updated": metadata.get("last_updated"),
        "root_dir": metadata.get("root_dir"),
        "message_count": len(messages),
        "model": session_data.get("model_spec", {}).get("title", "Unknown"),
        "first_message": first_message,
    }


def list_sessions(
    workdir: Optional[str] = None, history_base_dir: Optional[Path] = None
) -> List[Dict]:
    """
    List available developer sessions with metadata.

    Args:
        workdir: Optional working directory to filter sessions by.
                If provided, only sessions from this directory will be listed.
        history_base_dir: Optional base directory for history. If None, defaults to ~/.silica/personas/default

    Returns:
        List of session data dictionaries.
    """
    history_dir = get_history_dir(history_base_dir)

    if not history_dir.exists():
        return []

    sessions = []

    for session_dir in history_dir.iterdir():
        if not session_dir.is_dir():
            continue

        try:
            session_info = _read_session_info(session_dir)
            if session_info is None:
                continue

            # Filter by root directory if workdir is specified
            if workdir:
                session_root = os.path.normpath(session_info.get("root_dir", ""))
                workdir_norm = os.path.normpath(workdir)
                if session_root != workdir_norm:
                    continue

            sessions.append(session_info)

        except (json.JSONDecodeError, IOError, KeyError):
            # Skip invalid files
            continue

    # Sort by last_updated (newest first)
    sessions.sort(key=lambda x: x.get("last_updated", ""), reverse=True)

    return sessions


def get_session_data(
    session_id: str, history_base_dir: Optional[Path] = None
) -> Optional[Dict]:
    """
    Get data for a specific session.

    Args:
        session_id: ID or prefix of the session to retrieve.
        history_base_dir: Optional base directory for history. If None, defaults to ~/.silica/personas/default

    Returns:
        Session data dictionary if found, None otherwise.
    """
    history_dir = get_history_dir(history_base_dir)

    # Find matching session directory
    matching_ids = [
        d.name
        for d in history_dir.iterdir()
        if d.is_dir() and d.name.startswith(session_id)
    ]

    if not matching_ids:
        return None

    session_dir = history_dir / matching_ids[0]

    # Try v2 format first
    session_json = session_dir / "session.json"
    if session_json.exists():
        try:
            from silica.developer.session_store import SessionStore

            store = SessionStore(session_dir, agent_name="root")
            meta = store.read_session_meta()
            if meta and meta.get("version", 0) >= 2:
                context_msgs = store.read_context()
                history_msgs = store.read_history()
                metadata_entries = store.read_metadata()
                return {
                    **meta,
                    "messages": context_msgs,
                    "history_message_count": len(history_msgs),
                    "context_message_count": len(context_msgs),
                    "usage_count": len(metadata_entries),
                }
        except (json.JSONDecodeError, IOError):
            pass

    # Fall back to legacy root.json
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
    table.add_column("Last Updated", style="blue")
    table.add_column("Messages", style="magenta")
    table.add_column("First Message", style="white")
    table.add_column("Root Directory", style="bright_black")

    for session in sessions:
        # Parse and format dates
        updated = parse_iso_date(session.get("last_updated", ""))

        # Format session ID (use first 8 chars)
        short_id = session.get("session_id", "")[:8]

        # Truncate first message for display
        first_message = _truncate_message(session.get("first_message"), max_length=40)

        # Add row to table
        table.add_row(
            short_id,
            updated,
            str(session.get("message_count", 0)),
            first_message or "[dim]No messages[/dim]",
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
    history_base_dir = getattr(context, "history_base_dir", None)
    sessions = list_sessions(workdir, history_base_dir=history_base_dir)

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

    history_base_dir = getattr(context, "history_base_dir", None)
    session_data = get_session_data(session_id, history_base_dir=history_base_dir)
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


def format_session_option(
    session: Dict, terminal_width: int = 80, fixed_width: int = 0
) -> str:
    """Format a session for display in the interactive menu.

    Args:
        session: Session data dictionary
        terminal_width: Width of the terminal for calculating message space
        fixed_width: Fixed width for non-message parts (calculated if 0)

    Returns:
        Formatted string for menu display
    """
    short_id = session.get("session_id", "")[:8]
    updated = parse_iso_date(session.get("last_updated", ""))
    msg_count = session.get("message_count", 0)

    # Build the fixed-width prefix
    prefix = f"[{short_id}] {updated} ({msg_count} msgs)"

    # Calculate available space for the message
    # Account for: "  ❯ " prefix (4 chars), quotes around message (2 chars), space before message (1 char)
    overhead = 4 + 2 + 1 + len(prefix) + 1  # +1 for space after prefix
    available_width = max(20, terminal_width - overhead)

    first_message = _truncate_message(
        session.get("first_message"), max_length=available_width
    )

    if first_message:
        return f'{prefix} "{first_message}"'
    return prefix


async def interactive_resume(
    user_interface: Any,
    workdir: Optional[str] = None,
    history_base_dir: Optional[Path] = None,
    max_sessions: int = 10,
) -> Optional[str]:
    """Present an interactive menu to select a session to resume.

    Uses Rich and prompt_toolkit to display an interactive session picker
    that adapts to terminal width.

    Args:
        user_interface: The user interface for displaying the menu
        workdir: Optional working directory to filter sessions by
        history_base_dir: Optional base directory for history
        max_sessions: Maximum number of sessions to show in the menu

    Returns:
        Selected session ID, or None if cancelled
    """
    # Get available sessions
    sessions = list_sessions(workdir=workdir, history_base_dir=history_base_dir)

    if not sessions:
        return None

    # Limit to max_sessions
    sessions = sessions[:max_sessions]

    # Check if UI has our custom session picker method
    if hasattr(user_interface, "get_session_choice"):
        return await user_interface.get_session_choice(sessions)

    # Fallback to generic get_user_choice if available
    if hasattr(user_interface, "get_user_choice"):
        # Get terminal width for formatting
        console = Console()
        terminal_width = console.width or 80

        # Format options for the menu
        options = [
            format_session_option(session, terminal_width=terminal_width)
            for session in sessions
        ]

        # Present the menu
        question = "Select a session to resume:"
        result = await user_interface.get_user_choice(question, options)

        if result == "cancelled":
            return None

        # Check if user selected one of our options
        for i, option in enumerate(options):
            if result == option:
                return sessions[i]["session_id"]

        # User typed something else - try to match it as a session ID
        return result if result else None

    # No interactive UI available
    return None


def resume_session(session_id: str, history_base_dir: Optional[Path] = None) -> bool:
    """
    Resume a previous developer session.

    Args:
        session_id: ID or prefix of the session to resume.
        history_base_dir: Optional base directory for history. If None, defaults to ~/.silica/personas/default

    Returns:
        True if successful, False otherwise.
    """
    # Get basic session data to check metadata and root directory
    session_data = get_session_data(session_id, history_base_dir=history_base_dir)

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
        history_dir = get_history_dir(history_base_dir)
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
                silica_command = _reconstruct_command_from_list(stored_cli_args)
            else:
                # Fallback to basic command for unexpected format
                console.print(
                    f"Unexpected CLI args format, using basic command with model: {model}",
                    style="yellow",
                )
                silica_command = ["silica", "--model", model]
        else:
            # Fallback for sessions without stored CLI args (backward compatibility)
            console.print(
                f"No stored CLI args found, using basic command with model: {model}",
                style="yellow",
            )
            silica_command = ["silica", "--model", model]

        # Launch hdev with environment variable to resume the session
        os.environ["SILICA_DEVELOPER_SESSION_ID"] = full_session_id

        console.print(f"Executing: {' '.join(silica_command)}", style="blue")

        # Execute command (replace current process)
        os.execvp("silica", silica_command)

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
    command = ["silica"]

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
