from typing import Optional

from silica.developer.context import AgentContext
from silica.developer.sandbox import DoSomethingElseError
from .framework import tool


@tool
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


@tool(max_concurrency=1)
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


@tool
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


@tool(max_concurrency=1)
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
            # If match_text is not found, append replace_text to the end of the file
            new_content = content + "\n" + replace_text
            context.sandbox.write_file(path, new_content)
            return "Text not found. Content added to the end of the file."
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
