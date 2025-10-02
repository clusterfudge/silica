"""
Memory V2 Tools: Simplified single-file memory system with organic growth.

This module provides tools for interacting with the Memory V2 system,
which starts with a single memory file and organically grows through
agentic splitting when files become too large.
"""

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from silica.developer.context import AgentContext
from silica.developer.memory_v2 import LocalDiskStorage
from silica.developer.memory_v2.exceptions import (
    MemoryNotFoundError,
    MemoryStorageError,
)
from silica.developer.tools.framework import tool


@dataclass
class MemoryFileInfo:
    """Information about a memory file."""

    path: str
    size_bytes: int
    last_updated: datetime

    def __str__(self) -> str:
        """Format as readable string."""
        size_kb = self.size_bytes / 1024
        date_str = self.last_updated.strftime("%Y-%m-%d %H:%M:%S")
        return f"{self.path} ({size_kb:.1f} KB, updated {date_str})"


def _get_storage(context: "AgentContext") -> LocalDiskStorage:
    """
    Get or create storage instance for the context.

    For now, uses local disk storage. Future versions will support S3.
    """
    # Check if storage is already cached in context
    if not hasattr(context, "_memory_v2_storage"):
        # Get base path from environment or use default
        base_path = os.environ.get(
            "MEMORY_V2_PATH", str(Path.home() / ".silica" / "memory_v2")
        )
        context._memory_v2_storage = LocalDiskStorage(base_path)

    return context._memory_v2_storage


@tool
def read_memory(context: "AgentContext", path: str = "") -> str:
    """Read memory content from a specific path.

    Memory V2 uses a simple, organic structure that starts with a single root file
    and grows naturally. Each memory node can have both content and children,
    allowing seamless evolution from simple notes to complex hierarchies.

    **When to use this tool:**
    - Retrieve previously stored information
    - Check what's in a specific memory location
    - Review content before updating or splitting

    **Common patterns:**
    - `read_memory()` or `read_memory("")` - Read the root memory file
    - `read_memory("projects")` - Read the projects overview
    - `read_memory("projects/silica")` - Read detailed Silica information
    - `read_memory("knowledge/python")` - Read Python knowledge base

    Args:
        path: Path to the memory file to read. Use "" or omit for root memory.
              Examples: "projects", "projects/silica", "knowledge/python"

    Returns:
        The content of the memory file as a string.

    Raises:
        Error message if the memory file doesn't exist or cannot be read.

    **Tips:**
    - Start with the root to understand overall structure
    - Use list_memory_files() to see what paths exist
    - Memory paths are hierarchical: parent/child/grandchild
    - Each path can have both content and sub-paths
    """
    storage = _get_storage(context)

    # Handle empty path as root
    if not path:
        path = "memory"

    try:
        content = storage.read(path)
        return content
    except MemoryNotFoundError:
        return f"❌ Memory file not found: {path}\n\nUse list_memory_files() to see available paths."
    except MemoryStorageError as e:
        return f"❌ Error reading memory: {e}"


@tool
def write_memory(
    context: "AgentContext", content: str, path: str = "", append: bool = False
) -> str:
    """Write or update memory content at a specific path.

    This is the primary way to store information in Memory V2. The system will
    automatically create the necessary structure and handle file organization.
    When a file grows beyond 10KB, the system will prompt for splitting.

    **When to use this tool:**
    - Store new information or insights
    - Update existing memory with new details
    - Create new memory locations for organizing information
    - Document decisions, learnings, or context

    **Writing strategies:**
    - **Replace (default)**: Overwrites existing content completely
    - **Append mode**: Adds to the end of existing content (use sparingly)

    **Common patterns:**
    - `write_memory("Initial thoughts", "")` - Create/update root memory
    - `write_memory("Project overview", "projects")` - Create projects overview
    - `write_memory("Silica details", "projects/silica")` - Add child node
    - `write_memory("\\nNew insight", "knowledge", append=True)` - Append content

    Args:
        content: The content to write. Can be any text, markdown, code, etc.
        path: Where to write the content. Use "" for root memory.
              Examples: "projects", "projects/silica", "knowledge/python"
        append: If True, append to existing content instead of replacing.
                Default is False (replace). Use append cautiously.

    Returns:
        Success message with file size information, or error message if write fails.

    **Important notes:**
    - Files larger than 10KB will trigger a split warning
    - Each path can have both content AND child paths (organic growth!)
    - Parent paths are created automatically (e.g., writing to "a/b/c" creates "a" and "a/b")
    - Prefer replace over append for better content quality
    - Empty content is allowed (creates placeholder node)

    **Example workflow:**
    ```
    # Start simple
    write_memory("Working on Silica project", "")

    # Grow organically as needed
    write_memory("Python agent framework for autonomous development", "projects")
    write_memory("Uses pytest for testing, ruff for linting", "projects/silica")
    ```
    """
    storage = _get_storage(context)

    # Handle empty path as root
    if not path:
        path = "memory"

    try:
        # Handle append mode
        if append:
            try:
                existing = storage.read(path)
                content = existing + content
            except MemoryNotFoundError:
                # File doesn't exist yet, just write new content
                pass

        # Write the content
        storage.write(path, content)

        # Get size and check threshold
        size = storage.get_size(path)
        size_kb = size / 1024

        result = f"✅ Memory written successfully to: {path}\n"
        result += f"📊 Size: {size_kb:.2f} KB ({size} bytes)\n"

        # Warn if approaching or exceeding split threshold (10KB)
        if size > 10240:
            result += "\n⚠️  **File exceeds 10KB threshold!**\n"
            result += (
                "Consider splitting this content into smaller, more focused nodes.\n"
            )
            result += "This will make the memory system more organized and efficient.\n"
        elif size > 8192:  # Warn at 8KB (80% of threshold)
            result += "\n💡 File is getting large (>8KB).\n"
            result += "Consider organizing into child nodes soon.\n"

        return result

    except MemoryStorageError as e:
        return f"❌ Error writing memory: {e}"


@tool
def list_memory_files(context: "AgentContext") -> str:
    """List all memory files in the system.

    This tool helps you understand the current memory structure by showing
    all paths that contain content. Use this to:
    - Discover what information is stored
    - Find the right path for reading or writing
    - Understand the memory hierarchy
    - Identify areas for organization or cleanup

    **When to use this tool:**
    - Before reading to find the correct path
    - To get an overview of stored information
    - When planning where to write new content
    - To audit and organize memory structure

    Returns:
        Formatted list of all memory paths with their sizes and last update times.
        Returns "No memory files found" if the memory system is empty.

    **Output format:**
    ```
    Memory Files
    ============

    memory (2.3 KB, updated 2025-01-15 10:30:45)
    projects (1.8 KB, updated 2025-01-15 09:15:22)
    projects/silica (3.4 KB, updated 2025-01-15 10:25:33)
    knowledge (5.2 KB, updated 2025-01-14 16:45:11)
    knowledge/python (4.1 KB, updated 2025-01-15 08:20:15)

    Total: 5 files
    ```

    **Tips:**
    - Paths are shown in hierarchical order
    - Large files (>8KB) may need splitting
    - Empty memory system suggests starting with root: write_memory("content", "")
    - Use the paths shown here with read_memory() and write_memory()
    """
    storage = _get_storage(context)

    try:
        paths = storage.list_files()

        if not paths:
            return (
                "📭 No memory files found.\n\n"
                "Start by creating the root memory:\n"
                '  write_memory("Your initial thoughts", "")'
            )

        # Gather file info
        files_info: List[MemoryFileInfo] = []
        for path in paths:
            try:
                size = storage.get_size(path)
                modified = storage.get_modified_time(path)
                files_info.append(MemoryFileInfo(path, size, modified))
            except Exception:
                # Skip files we can't read info for
                continue

        # Format output
        result = "Memory Files\n"
        result += "=" * 60 + "\n\n"

        for info in files_info:
            size_kb = info.size_bytes / 1024
            date_str = info.last_updated.strftime("%Y-%m-%d %H:%M:%S")

            # Add size warning emoji for large files
            warning = ""
            if info.size_bytes > 10240:
                warning = " ⚠️  EXCEEDS 10KB - Consider splitting"
            elif info.size_bytes > 8192:
                warning = " 💡 Getting large"

            result += f"{info.path}\n"
            result += f"  📊 {size_kb:.2f} KB | 📅 {date_str}{warning}\n\n"

        result += f"Total: {len(files_info)} file(s)\n"

        return result

    except MemoryStorageError as e:
        return f"❌ Error listing memory files: {e}"


@tool
def delete_memory(context: "AgentContext", path: str) -> str:
    """Delete a memory file.

    **⚠️  CAUTION: This operation is permanent!**

    Use this tool to remove memory content that is:
    - No longer relevant or accurate
    - Redundant with other entries
    - Being reorganized into a different structure
    - Temporary or experimental

    **When to use this tool:**
    - Clean up outdated information
    - Remove duplicate content
    - Restructure memory hierarchy
    - Delete test or experimental entries

    **What happens:**
    - The content file is deleted
    - If the node has NO children, the directory is also removed
    - If the node HAS children, they remain accessible
    - The deletion is immediate and cannot be undone

    Args:
        path: Path to the memory file to delete.
              Examples: "projects", "old_notes", "temp/experimental"

    Returns:
        Success message if deleted, or error message if the path doesn't exist
        or cannot be deleted.

    **Important notes:**
    - Parent paths remain even if their content is deleted (if they have children)
    - To fully remove a branch, delete children first, then parent
    - Consider backing up important content before deleting
    - Deletion does not affect other memory files

    **Example workflow:**
    ```
    # Delete a single entry
    delete_memory("temp/experimental")

    # Reorganize: read, write elsewhere, then delete
    content = read_memory("old_location")
    write_memory(content, "new_location")
    delete_memory("old_location")
    ```
    """
    storage = _get_storage(context)

    try:
        storage.delete(path)
        return f"✅ Memory file deleted: {path}"
    except MemoryNotFoundError:
        return f"❌ Memory file not found: {path}\n\nUse list_memory_files() to see available paths."
    except MemoryStorageError as e:
        return f"❌ Error deleting memory: {e}"
