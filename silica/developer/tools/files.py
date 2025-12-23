import json
from typing import Optional

from silica.developer.context import AgentContext
from silica.developer.sandbox import DoSomethingElseError
from .framework import tool


@tool(group="Files")
async def read_file(context: "AgentContext", path: str):
    """Read and return the contents of a file from the sandbox.

    Args:
        path: Path to the file to read
    """
    try:
        return await context.sandbox.read_file(path)
    except PermissionError:
        return f"Error: No read permission for {path}"
    except DoSomethingElseError:
        raise  # Re-raise to be handled by higher-level components
    except Exception as e:
        return f"Error reading file: {str(e)}"


@tool(group="Files", max_concurrency=1)
def write_file(context: "AgentContext", path: str, content: str):
    """Write content to a file in the sandbox.

    Args:
        path: Path where the file should be written
        content: Content to write to the file
    """
    try:
        context.sandbox.write_file(path, content)
        return "File written successfully"
    except PermissionError:
        return f"Error: No write permission for {path}"
    except DoSomethingElseError:
        raise  # Re-raise to be handled by higher-level components
    except Exception as e:
        return f"Error writing file: {str(e)}"


@tool(group="Files")
def list_directory(
    context: "AgentContext", path: str, recursive: Optional[bool] = None
):
    """List contents of a directory in the sandbox.

    Args:
        path: Path to the directory to list
        recursive: If True, list contents recursively (optional)
    """
    try:
        contents = context.sandbox.get_directory_listing(
            path, recursive=bool(recursive) if recursive is not None else False
        )

        result = f"Contents of {path}:\n"
        for item in contents:
            result += f"{item}\n"
        return result
    except Exception as e:
        return f"Error listing directory: {str(e)}"


@tool(group="Files", max_concurrency=1)
async def edit_file(
    context: "AgentContext", path: str, match_text: str, replace_text: str
):
    """Make a targeted edit to a file in the sandbox by replacing specific text.

    Args:
        path: Path to the file to edit
        match_text: Text to find in the file
        replace_text: Text to replace the matched text with
    """
    try:
        content = await context.sandbox.read_file(path)

        # Check if the match_text is unique
        if content.count(match_text) > 1:
            return "Error: The text to match is not unique in the file."
        elif content.count(match_text) == 0:
            # If match_text is not found, return an error
            return f"Error: Could not find the specified text to match in {path}. Please verify the exact text exists in the file."
        else:
            # Replace the matched text
            new_content = content.replace(match_text, replace_text, 1)
            context.sandbox.write_file(path, new_content)
            return "File edited successfully"
    except PermissionError:
        return f"Error: No read or write permission for {path}"
    except DoSomethingElseError:
        raise  # Re-raise to be handled by higher-level components
    except Exception as e:
        return f"Error editing file: {str(e)}"


@tool(group="Files", max_concurrency=1)
async def multi_edit(
    context: "AgentContext",
    path: str,
    edits: str,
):
    """Make multiple targeted edits to a file in a single atomic operation.

    All matches are validated before any changes are made. If any match fails,
    no changes are applied. Edits are applied in reverse order (bottom to top)
    to preserve line numbers for subsequent edits.

    Args:
        path: Path to the file to edit
        edits: JSON array of edit objects, each with "match" and "replace" keys.
               Example: [{"match": "old text", "replace": "new text"}, ...]
    """
    try:
        content = await context.sandbox.read_file(path)
    except PermissionError:
        return f"Error: No read permission for {path}"
    except DoSomethingElseError:
        raise
    except Exception as e:
        return f"Error reading file: {str(e)}"

    # Parse edits JSON
    try:
        edit_list = json.loads(edits)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON for edits: {e}"

    if not isinstance(edit_list, list):
        return "Error: edits must be a JSON array"

    if not edit_list:
        return "Error: No edits provided"

    # Validate edit objects
    for i, edit in enumerate(edit_list):
        if not isinstance(edit, dict):
            return (
                f"Error: Edit {i + 1} must be an object with 'match' and 'replace' keys"
            )
        if "match" not in edit:
            return f"Error: Edit {i + 1} missing 'match' key"
        if "replace" not in edit:
            return f"Error: Edit {i + 1} missing 'replace' key"

    # Find all matches and validate they exist and are unique
    matches = []
    for i, edit in enumerate(edit_list):
        match_text = edit["match"]
        count = content.count(match_text)

        if count == 0:
            preview = match_text[:50] + "..." if len(match_text) > 50 else match_text
            preview = preview.replace("\n", "\\n")
            return f'Error: Edit {i + 1} - match text not found: "{preview}"'

        if count > 1:
            preview = match_text[:50] + "..." if len(match_text) > 50 else match_text
            preview = preview.replace("\n", "\\n")
            return f'Error: Edit {i + 1} - match text is not unique ({count} occurrences): "{preview}"'

        start = content.find(match_text)
        end = start + len(match_text)
        line_num = content[:start].count("\n") + 1

        matches.append(
            {
                "index": i,
                "start": start,
                "end": end,
                "line": line_num,
                "match": match_text,
                "replace": edit["replace"],
            }
        )

    # Check for overlapping edits
    matches_sorted = sorted(matches, key=lambda m: m["start"])
    for i in range(len(matches_sorted) - 1):
        curr = matches_sorted[i]
        next_m = matches_sorted[i + 1]
        if curr["end"] > next_m["start"]:
            return (
                f"Error: Overlapping edits - Edit {curr['index'] + 1} (line {curr['line']}) "
                f"overlaps with Edit {next_m['index'] + 1} (line {next_m['line']})"
            )

    # Apply edits in reverse order (bottom to top) to preserve positions
    matches_reversed = sorted(matches, key=lambda m: m["start"], reverse=True)

    for m in matches_reversed:
        content = content[: m["start"]] + m["replace"] + content[m["end"] :]

    # Write the file
    try:
        context.sandbox.write_file(path, content)
    except PermissionError:
        return f"Error: No write permission for {path}"
    except DoSomethingElseError:
        raise
    except Exception as e:
        return f"Error writing file: {str(e)}"

    # Build summary
    summary_lines = [f"Successfully applied {len(edit_list)} edit(s) to {path}:"]
    for m in matches:
        preview = m["match"][:40].replace("\n", "\\n")
        if len(m["match"]) > 40:
            preview += "..."
        summary_lines.append(f'  Line {m["line"]}: "{preview}"')

    return "\n".join(summary_lines)
