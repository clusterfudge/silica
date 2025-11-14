"""
Tools for reading and modifying persona files.

These tools allow the model to inspect and update its own persona definition,
enabling self-improvement and adaptation based on user preferences.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from silica.developer.context import AgentContext
from silica.developer.tools.framework import tool


def _log_persona_edit(
    persona_dir: Path,
    action: str,
    persona_name: str,
    content_length: int,
    backup_path: str | None = None,
) -> None:
    """Log a persona edit to persona.log.jsonl.

    Args:
        persona_dir: Path to persona directory
        action: Action performed ("write", "create", etc.)
        persona_name: Name of the persona
        content_length: Length of the new content
        backup_path: Optional path to backup file
    """
    log_file = persona_dir / "memory" / "persona.log.jsonl"

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "persona_name": persona_name,
        "content_length": content_length,
    }

    if backup_path:
        log_entry["backup_path"] = backup_path

    # Append to log file
    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


@tool
def read_persona(context: AgentContext) -> str:
    """Read the content of the current persona file.

    This tool reads the persona.md file for the currently running persona.
    This allows the model to inspect its own instructions and understand what
    can be modified.

    Returns:
        The content of the persona.md file, or an error message if not found.

    Examples:
        >>> read_persona()  # Read current persona
    """
    try:
        persona_dir = context.history_base_dir
        persona_file = persona_dir / "memory" / "persona.md"

        if not persona_file.exists():
            return f"Error: Persona file not found at {persona_file}"

        with open(persona_file, "r") as f:
            content = f.read()

        persona_name = persona_dir.name
        return f"Persona: {persona_name}\nPath: {persona_file}\n\n{content}"

    except Exception as e:
        return f"Error reading persona: {str(e)}"


@tool
def write_persona(context: AgentContext, content: str) -> str:
    """Write or update the current persona file.

    This tool writes new content to the current persona's persona.md file.
    Before writing, it creates a timestamped backup of the existing file
    (if it exists) and logs the edit to persona.log.jsonl.

    IMPORTANT: This modifies the persona that controls the model's own behavior.
    Use carefully and ensure the new content maintains clear, actionable instructions.

    Args:
        content: The new persona content (markdown format)

    Returns:
        Success message with backup information, or error message.

    Examples:
        >>> write_persona(content="# My Custom Persona\\n\\nBe concise and helpful.")
    """
    # Validate content
    if not content or not content.strip():
        return "Error: Persona content cannot be empty"

    if len(content) > 100000:  # 100KB limit
        return "Error: Persona content too large (max 100KB)"

    try:
        persona_dir = context.history_base_dir
        persona_name = persona_dir.name

        # Ensure memory directory exists
        memory_dir = persona_dir / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)

        persona_file = memory_dir / "persona.md"

        # Create backup if file exists
        backup_path = None
        if persona_file.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = memory_dir / f"persona.backup.{timestamp}.md"

            with open(persona_file, "r") as f:
                old_content = f.read()

            with open(backup_file, "w") as f:
                f.write(old_content)

            backup_path = backup_file.name
            action = "write"
        else:
            action = "create"

        # Write new content
        with open(persona_file, "w") as f:
            f.write(content)

        # Log the edit
        _log_persona_edit(
            persona_dir=persona_dir,
            action=action,
            persona_name=persona_name,
            content_length=len(content),
            backup_path=backup_path,
        )

        result = f"Successfully {action}d persona: {persona_name}\n"
        result += f"File: {persona_file}\n"
        result += f"Length: {len(content)} characters\n"

        if backup_path:
            result += f"Backup: {backup_path}\n"

        result += (
            "\nThe updated persona will take effect on the next system prompt render."
        )

        return result

    except Exception as e:
        return f"Error writing persona: {str(e)}"
