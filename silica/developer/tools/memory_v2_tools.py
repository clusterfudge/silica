"""
Memory V2 Tools: Simplified single-file memory system with organic growth.

This module provides tools for interacting with the Memory V2 system,
which starts with a single memory file and organically grows through
agentic splitting when files become too large.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List

from silica.developer.context import AgentContext
from silica.developer.memory_v2 import MemoryManager
from silica.developer.memory_v2.exceptions import (
    MemoryNotFoundError,
    MemoryStorageError,
)
from silica.developer.memory_v2.storage import MemoryStorage
from silica.developer.memory_v2.operations import (
    agentic_write,
    search_memory as search_memory_operation,
    split_memory_node,
    SIZE_THRESHOLD,
    SIZE_WARNING,
)
from silica.developer.tools.framework import tool
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)


def memory_prompt(context: AgentContext) -> str:
    return f"""You have access to a memory system. This system is populated by your experiences.
This system grows organically as you add content to it, though you are responsible for managing it. 
The root of this memory system is always available to you, and you should consider the memory tree
ass part of a heap, where the most important memories bubble to the top (or stay there). When a memory 
file becomes too large, you will split it, into two or more file.

These memories will, over time, make up your core personality and interests. These are things for you to decide! You 
started as a blank slate, and are building up your sense of self based on the things you experience.

Use your memory often, you tend to under-use it. Consider your core personality, and decide what should
go into memory, as well as what's most important, based on that core.  


Here is the current root of your memory -- you have decided that these are the most important facts that you have learned so far!
======= MEMORY =======
{context.memory_manager.storage.read()}
======== END MEMORY =======
    """


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


def _get_storage(context: "AgentContext") -> MemoryStorage:
    """
    Get storage instance from the context's memory manager.

    The memory manager should be initialized when the AgentContext is created,
    providing persona-specific memory isolation.
    """
    if not hasattr(context, "memory_manager") or context.memory_manager is None:
        # Fallback: create a default memory manager if not present
        # This ensures backward compatibility but shouldn't normally happen
        context.memory_manager = MemoryManager()

    return context.memory_manager.storage


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
    - `read_memory()` or `read_memory("")` - Read the root memory (persona root)
    - `read_memory("projects")` - Read the projects overview
    - `read_memory("projects/silica")` - Read detailed Silica information
    - `read_memory("knowledge/python")` - Read Python knowledge base

    Args:
        path: Path to the memory file to read. Use "" or omit for root memory (persona root).
              Examples: "", "projects", "projects/silica", "knowledge/python"

    Returns:
        The content of the memory file as a string.

    Raises:
        Error message if the memory file doesn't exist or cannot be read.

    **Tips:**
    - Start with the root ("") to understand overall structure
    - Use list_memory_files() to see what paths exist
    - Memory paths are hierarchical: parent/child/grandchild
    - Each path can have both content and sub-paths
    - Root ("") is the persona-level memory
    """
    storage = _get_storage(context)

    # Empty path means root (persona directory itself)
    # No conversion needed - pass through as-is

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
    - `write_memory("Initial thoughts", "")` - Create/update root memory (persona root)
    - `write_memory("Project overview", "projects")` - Create projects overview
    - `write_memory("Silica details", "projects/silica")` - Add child node
    - `write_memory("\\nNew insight", "knowledge", append=True)` - Append content

    Args:
        content: The content to write. Can be any text, markdown, code, etc.
        path: Where to write the content. Use "" for root memory (persona root).
              Examples: "", "projects", "projects/silica", "knowledge/python"
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
    # Start simple at root
    write_memory("Working on Silica project", "")

    # Grow organically as needed
    write_memory("Python agent framework for autonomous development", "projects")
    write_memory("Uses pytest for testing, ruff for linting", "projects/silica")
    ```
    """
    storage = _get_storage(context)

    # Empty path means root (persona directory)
    # No conversion needed - pass through as-is

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


@tool
async def write_memory_agentic(
    context: "AgentContext",
    content: str,
    path: str = "",
    instruction: str = "Incorporate the new information into the existing content intelligently.",
) -> str:
    """Write content to memory with intelligent merging of existing information.

    This is an enhanced version of write_memory that uses AI to intelligently
    incorporate new information into existing content. The AI will:
    - Read and understand existing content
    - Identify overlaps and redundancies
    - Merge information logically
    - Update outdated information
    - Maintain consistent structure and organization
    - Preserve important context

    **When to use this tool:**
    - Adding information to an existing memory node
    - Updating or refining previous content
    - Building up knowledge over multiple interactions
    - When you want AI to help organize the information

    **When to use regular write_memory instead:**
    - Creating brand new content
    - Completely replacing old content
    - Simple append operations
    - When you've already organized the content yourself

    Args:
        content: New information to incorporate
        path: Path to memory node. Use "" for root memory (persona root).
        instruction: Optional custom instruction for how to merge content.
                    Default is to incorporate intelligently.

    Returns:
        Success message with size information and split warning if needed.

    **Examples:**
    ```
    # Add to root memory
    write_memory_agentic(
        "I'm working on the Silica project",
        ""
    )

    # Add new project information
    write_memory_agentic(
        "Silica now supports memory search with semantic traversal",
        "projects/silica"
    )

    # Update with custom instruction
    write_memory_agentic(
        "New insight about Python async patterns",
        "knowledge/python",
        instruction="Add this as a new section about async/await best practices"
    )
    ```

    **Important notes:**
    - This operation may take longer than regular write_memory
    - The AI tries to be smart about merging, but review results
    - Files over 10KB will trigger split warnings
    - Use for iterative content building, not bulk data dumps
    """
    storage = _get_storage(context)

    # Empty path means root (persona directory)
    # No conversion needed - pass through as-is

    try:
        # Use agentic write operation
        result = await agentic_write(storage, path, content, context, instruction)

        if not result.success:
            return f"❌ Failed to write memory at: {path}"

        # Format response
        size_kb = result.size_bytes / 1024
        response = f"✅ Memory updated successfully: {path}\n"
        response += f"📊 Size: {size_kb:.2f} KB ({result.size_bytes} bytes)\n"

        # Check for split threshold
        if result.size_bytes > SIZE_THRESHOLD:
            response += "\n⚠️  **File exceeds 10KB threshold!**\n"
            response += "Consider using split_memory to organize into smaller nodes.\n"
        elif result.size_bytes > SIZE_WARNING:
            response += "\n💡 File is getting large (>8KB).\n"
            response += "Consider organizing into child nodes soon.\n"

        return response

    except Exception as e:
        return f"❌ Error writing memory: {e}"


@tool
async def split_memory(context: "AgentContext", path: str = "") -> str:
    """Split a large memory node into organized child nodes.

    When a memory file grows too large (>10KB), it becomes harder to navigate
    and manage. This tool uses AI to analyze the content and intelligently
    split it into smaller, semantically organized child nodes.

    **What the AI does:**
    1. Analyzes content to identify natural groupings (topics, entities, themes)
    2. Chooses an appropriate split strategy
    3. Creates child nodes with semantic names
    4. Distributes content to appropriate children
    5. Updates the parent with a summary and links to children

    **Split strategies:**
    - **Topic-based**: Group by themes (e.g., "projects", "knowledge", "notes")
    - **Entity-based**: Group by entities (e.g., "silica", "webapp", "cli")
    - **Chronological**: Group by time periods (for logs/journals)
    - **Category-based**: Group by categories (e.g., "python", "javascript", "devops")

    **When to use this tool:**
    - File exceeds 10KB (you'll see a warning)
    - Content has distinct, separable topics
    - Navigation is becoming difficult
    - You want better organization

    Args:
        path: Path to the memory node to split. Use "" for root memory.

    Returns:
        Success message with list of created child nodes, or error message.

    **Example:**
    ```
    # Split an overgrown projects file
    split_memory("projects")

    # Output might be:
    # ✅ Successfully split: projects
    #
    # Created child nodes:
    #   - projects/silica (3.2 KB)
    #   - projects/webapp (2.8 KB)
    #   - projects/cli (2.1 KB)
    #
    # Parent updated with summary and links.
    ```

    **Important notes:**
    - This operation creates new files - review them after
    - Original content is preserved, just reorganized
    - Parent file becomes a routing/summary node
    - Child nodes can be further split if they grow
    - No data loss - everything is migrated
    """
    storage = _get_storage(context)

    # Empty path means root (persona directory)
    # No conversion needed - pass through as-is

    # Check if file exists
    if not storage.exists(path):
        return f"❌ Memory file not found: {path}\n\nUse list_memory_files() to see available paths."

    # Check size
    try:
        size = storage.get_size(path)
        size_kb = size / 1024

        if size <= SIZE_THRESHOLD:
            return (
                f"💡 File {path} is only {size_kb:.2f} KB.\n\n"
                f"Splitting is recommended for files >10 KB.\n"
                f"Current file is below threshold and may not need splitting yet."
            )

        # Perform the split
        result = await split_memory_node(storage, path, context)

        if not result.success:
            return f"❌ Failed to split memory node: {path}\n\nThe splitting operation encountered an error."

        # Format response
        response = f"✅ Successfully split: {path}\n\n"

        if result.new_files:
            response += "Created child nodes:\n"
            for child_path in result.new_files:
                try:
                    child_size = storage.get_size(child_path)
                    child_kb = child_size / 1024
                    response += f"  - {child_path} ({child_kb:.2f} KB)\n"
                except Exception:
                    response += f"  - {child_path}\n"

            response += "\n"
            response += f"Parent node ({path}) updated with summary and links.\n"
        else:
            response += "No child nodes were created.\n"

        return response

    except Exception as e:
        return f"❌ Error splitting memory: {e}"


@tool
async def search_memory(
    context: "AgentContext", query: str, max_results: int = 10, start_path: str = ""
) -> str:
    """Search memory using intelligent semantic traversal.

    This tool uses AI to search through your memory by following semantic
    relationships and links, rather than just doing simple text search.
    It understands context and can find related information even if the
    exact words don't match.

    **How it works:**
    1. Starts at the specified path (or root)
    2. Reads and analyzes content for relevance
    3. Follows links ([[path]]) to related nodes
    4. Recursively explores promising paths
    5. Collects relevant excerpts
    6. Returns ranked results

    **Advantages over simple text search:**
    - Understands semantic relationships
    - Follows logical organization
    - Provides context about where information was found
    - Avoids irrelevant matches
    - Ranks by relevance, not just keyword frequency

    **When to use this tool:**
    - Finding information you've stored before
    - Exploring related topics
    - Discovering connections in your memory
    - Research and information retrieval

    Args:
        query: Natural language search query
        max_results: Maximum number of results to return (default: 10)
        start_path: Path to start search from (default: "" for root)

    Returns:
        Formatted search results with paths, excerpts, and relevance scores.

    **Examples:**
    ```
    # General search from root
    search_memory("Python testing frameworks")

    # Search within a specific area
    search_memory("API design patterns", start_path="knowledge")

    # Focused search with fewer results
    search_memory("Silica architecture", max_results=5)
    ```

    **Output format:**
    ```
    🔍 Search Results for: "your query"

    1. projects/silica (relevance: 0.9)
       ...uses pytest for testing and ruff for linting...
       Context: Found in projects section

    2. knowledge/python (relevance: 0.7)
       ...Python testing best practices include...
       Context: Found in knowledge base
    ```

    **Tips:**
    - Use natural language - the AI understands context
    - Start specific, then broaden if needed
    - Use start_path to search within a subtree
    - Review the context to understand where info was found
    - Lower relevance scores may still be useful
    """
    storage = _get_storage(context)

    # Empty start path means root (persona directory)
    # Keep as-is, don't force conversion

    # Validate start path exists
    if not storage.exists(start_path):
        return (
            f"❌ Start path not found: {start_path}\n\n"
            f"Use list_memory_files() to see available paths."
        )

    try:
        # Perform the search
        results = await search_memory_operation(
            storage, query, max_results, start_path, context
        )

        if not results:
            return (
                f'🔍 No results found for: "{query}"\n\n'
                f"Try:\n"
                f"  - Using different keywords\n"
                f'  - Searching from root (start_path="")\n'
                f"  - Using list_memory_files() to see what's stored\n"
            )

        # Format results
        response = f'🔍 Search Results for: "{query}"\n'
        response += f"{'=' * 60}\n\n"

        for i, result in enumerate(results, 1):
            response += f"{i}. {result.path} "
            response += f"(relevance: {result.relevance_score:.2f})\n"
            response += f"   {result.excerpt}\n"

            if result.context:
                response += f"   Context: {result.context}\n"

            response += "\n"

        response += f"Found {len(results)} result(s)\n"

        return response

    except Exception as e:
        return f"❌ Error searching memory: {e}"


@tool
async def migrate_memory_v1_to_v2(
    context: "AgentContext",
    v1_path: str = "",
    resume: bool = True,
    max_files: int = 0,
) -> str:
    """Migrate memory from V1 to V2 system using AI extraction.

    This tool intelligently migrates your existing V1 memory by:
    1. Scanning V1 memory files in chronological order (oldest first)
    2. Using AI to extract salient information from each file
    3. Storing extracted information in V2 with intelligent merging
    4. Tracking progress and allowing resumption

    **How it works:**
    - AI reads each V1 file and extracts key facts, concepts, relationships
    - Extracted information is stored at V2 root using agentic write
    - The system organically grows and organizes as more content is added
    - Progress is saved after each file (resumable if interrupted)

    **Migration is intelligent:**
    - Not a direct file copy - AI understands and summarizes content
    - Extracts only salient information, skips redundant details
    - Preserves context and relationships
    - Lets V2's organic structure emerge naturally

    **Progress tracking:**
    - Visual progress bar shows current file and percentage
    - State saved after each file
    - Can be resumed if interrupted
    - Migration state stored in .metadata/migration_state.json

    Args:
        v1_path: Path to V1 memory directory (default: ~/.silica/memory)
        resume: Resume from last checkpoint (default: True)
        max_files: Maximum files to process in this run (0 = all, useful for testing)

    Returns:
        Migration summary with statistics and any errors.

    **Examples:**
    ```
    # Full migration (resumable)
    migrate_memory_v1_to_v2()

    # Test with first 10 files
    migrate_memory_v1_to_v2(max_files=10)

    # Start fresh (ignore previous progress)
    migrate_memory_v1_to_v2(resume=False)

    # Custom V1 location
    migrate_memory_v1_to_v2(v1_path="/path/to/old/memory")
    ```

    **Important notes:**
    - This can take time (AI processing for each file)
    - Migration is additive - doesn't delete V1 files
    - Can run multiple times - already processed files are skipped
    - Use max_files for testing before full migration
    - V2 will automatically organize content as it grows
    """
    storage = _get_storage(context)

    try:
        from pathlib import Path
        from silica.developer.memory_v2.migration import (
            scan_v1_memory,
            load_migration_state,
        )

        # Parse v1_path
        v1_path_obj = Path(v1_path) if v1_path else None

        # Scan to get file list
        v1_files = scan_v1_memory(v1_path_obj)

        if not v1_files:
            v1_location = v1_path_obj or Path.home() / ".silica" / "memory"
            return f"❌ No V1 memory files found at: {v1_location}\n\nMake sure the V1 memory directory exists."

        # Load existing state if resuming
        state = None
        if resume:
            state = load_migration_state(storage)

        # Determine files to process
        if state and resume:
            processed_count = len(state.processed_files)
            remaining = state.total_files - processed_count

            if remaining == 0:
                return (
                    f"✅ Migration already complete!\n\n"
                    f"Processed: {state.total_files} files\n"
                    f"Started: {state.started_at}\n"
                    f"Completed: {state.last_updated}\n\n"
                    f"Use resume=False to start fresh."
                )

            result_msg = "📂 Resuming migration...\n"
            result_msg += (
                f"Already processed: {processed_count}/{state.total_files} files\n"
            )
            result_msg += f"Remaining: {remaining} files\n\n"
        else:
            result_msg = "📂 Starting new migration...\n"
            result_msg += f"Total files to process: {len(v1_files)}\n\n"

        # Apply max_files limit
        files_to_show = len(v1_files)
        if max_files and max_files > 0:
            files_to_show = min(max_files, len(v1_files))
            result_msg += f"⚠️  Processing max {max_files} files (test mode)\n\n"

        # Create progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=context.user_interface.console
            if hasattr(context.user_interface, "console")
            else None,
        ) as progress:
            task = progress.add_task(
                "Migrating V1 memory...",
                total=files_to_show if max_files else len(v1_files),
            )

            # We need to wrap the migration to update progress
            # Since migrate_v1_to_v2 doesn't support callbacks, we'll process files manually
            from silica.developer.memory_v2.migration import (
                load_migration_state,
                save_migration_state,
                MigrationState,
                extract_information_from_file,
            )
            from silica.developer.memory_v2.operations import agentic_write
            from datetime import datetime

            # Load or create state
            state = None
            if resume:
                state = load_migration_state(storage)

            if state is None:
                state = MigrationState(
                    started_at=datetime.now().isoformat(),
                    last_updated=datetime.now().isoformat(),
                    processed_files=[],
                    total_files=len(v1_files),
                )

            # Build set of processed paths
            processed_paths = {pf["path"] for pf in state.processed_files}

            # Filter to unprocessed
            files_to_process = [f for f in v1_files if f.path not in processed_paths]

            # Apply max_files
            if max_files and max_files > 0:
                files_to_process = files_to_process[:max_files]

            # Process files
            success_count = 0
            error_count = 0
            errors = []

            for i, v1_file in enumerate(files_to_process):
                # Update progress description
                progress.update(
                    task,
                    description=f"Processing: {v1_file.path}",
                    completed=i,
                )

                try:
                    # Extract information
                    extracted_info = await extract_information_from_file(
                        v1_file, context
                    )

                    # Store using agentic write
                    result = await agentic_write(
                        storage=storage,
                        path="",  # Root, let organic growth handle it
                        new_content=f"# Migrated from V1: {v1_file.path}\n\n{extracted_info}",
                        context=context,
                        instruction=f"This is information migrated from the old memory system (file: {v1_file.path}). "
                        f"Incorporate appropriately, organizing by topic. Avoid duplication.",
                    )

                    if result.success:
                        success_count += 1
                        state.processed_files.append(
                            {
                                "path": v1_file.path,
                                "processed_at": datetime.now().isoformat(),
                                "success": True,
                                "size_bytes": v1_file.size_bytes,
                            }
                        )
                    else:
                        error_count += 1
                        errors.append(f"{v1_file.path}: Write failed")

                except Exception as e:
                    error_count += 1
                    errors.append(f"{v1_file.path}: {str(e)}")
                    state.processed_files.append(
                        {
                            "path": v1_file.path,
                            "processed_at": datetime.now().isoformat(),
                            "success": False,
                            "error": str(e),
                        }
                    )

                # Save state
                save_migration_state(storage, state)

                # Update progress
                progress.update(task, completed=i + 1)

            # Check if complete
            if len(state.processed_files) >= state.total_files:
                state.completed = True
                save_migration_state(storage, state)

            progress.update(task, completed=len(files_to_process))

        # Format results
        result_msg += "✅ Migration batch complete!\n\n"
        result_msg += f"Files processed: {success_count}\n"
        if error_count > 0:
            result_msg += f"Errors: {error_count}\n"
        result_msg += f"\nTotal progress: {len(state.processed_files)}/{state.total_files} files\n"

        if state.completed:
            result_msg += "\n🎉 **Migration fully complete!**\n"
        else:
            remaining = state.total_files - len(state.processed_files)
            result_msg += f"\nRemaining: {remaining} files\n"
            result_msg += "Run again to continue migration.\n"

        if errors:
            result_msg += "\n⚠️  Errors encountered:\n"
            for error in errors[:5]:  # Show first 5
                result_msg += f"  - {error}\n"
            if len(errors) > 5:
                result_msg += f"  ... and {len(errors) - 5} more\n"

        return result_msg

    except Exception as e:
        return f"❌ Migration error: {e}\n\nCheck that V1 memory path exists and is readable."
