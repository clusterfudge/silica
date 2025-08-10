import json
from pathlib import Path
from typing import Optional, Dict, Any

from silica.developer.context import AgentContext
from silica.developer.tools import agent
from silica.developer.tools.framework import tool
from silica.developer.utils import render_tree


@tool
def get_memory_tree(
    context: "AgentContext", prefix: Optional[str] = None, depth: int = -1
) -> str:
    """Get the memory tree structure starting from the given prefix.
    Returns a tree with only node names (no content) in a hierarchical structure,
    rendered using ASCII characters.

    Args:
        prefix: The prefix path to start from (None for root)
        depth: How deep to traverse (-1 for unlimited)
    """
    prefix_path = Path(prefix) if prefix else None
    result = context.memory_manager.get_tree(prefix_path, depth)

    if not result["success"]:
        return result["error"]

    # Render the tree using ASCII characters
    lines = []

    # Start rendering from the root
    render_tree(lines, result["items"], is_root=True)

    # If no items were rendered, return a message
    if not lines:
        return "Empty memory tree."

    # Convert lines to a single string
    return "\n".join(lines)


@tool
async def search_memory(
    context: "AgentContext", query: str, prefix: Optional[str] = None
) -> str:
    """Search memory with the given query.

    Args:
        query: Search query
        prefix: Optional path prefix to limit search scope

    Returns:
        a list of memory paths (these should be used for read/write_memory_entry tools.
    """
    memory_dir = context.memory_manager.base_dir
    search_path = memory_dir

    if prefix:
        search_path = memory_dir / prefix
        if not search_path.exists() or not search_path.is_dir():
            return f"Error: Path {prefix} does not exist or is not a directory"

    try:
        # Use the agent tool to kick off an agentic search using grep
        from silica.developer.tools.subagent import agent

        prompt = f"""
        You are an expert in using grep to search through files. 
        
        TASK: Search through memory entries in the directory "{search_path}" to find information relevant to this query: "{query}"
        
        The memory system stores entries as:
        1. .md files for content
        2. .metadata.json files for metadata
        
        Use grep to search through the .md files and find matches for the query.
        
        Here are some grep commands you might use:
        - `grep -r --include="*.md" "{query}" {search_path}`
        - `grep -r --include="*.md" -i "{query}" {search_path}` (case insensitive)
        - `grep -r --include="*.md" -l "{query}" {search_path}` (just list files)
        
        After finding matches, examine the matching files to provide context around the matches. Format your results as:
        
        ## Search Results
        
        1. [Path to memory]: Brief explanation of why this matches
        2. [Path to memory]: Brief explanation of why this matches
        
        For the paths, strip off the .md extension and the base directory path to present clean memory paths.
        
        If no results match, say "No matching memory entries found."
        """

        # Use the subagent tool to perform the search with shell_execute tool
        result = await agent(
            context=context,
            prompt=prompt,
            tool_names="shell_execute",  # Allow grep commands
            model="smart",
        )

        return result
    except Exception as e:
        return f"Error searching memory: {str(e)}"


def _format_entry_as_markdown(entry_data: Dict[str, Any]) -> str:
    """Format a file entry as markdown.

    Args:
        entry_data: The structured entry data

    Returns:
        A markdown-formatted string representation
    """
    if not entry_data["success"]:
        return f"Error: {entry_data['error']}"

    if entry_data["type"] == "file":
        result = f"Memory entry: {entry_data['path']}\n\n"
        result += f"Content:\n{entry_data['content']}\n\n"
        result += "Metadata:\n"
        for key, value in entry_data["metadata"].items():
            result += f"- {key}: {value}\n"
    elif entry_data["type"] == "directory":
        result = f"Directory: {entry_data['path']}\n\nContained paths:\n"

        if not entry_data["items"]:
            result += "  (empty directory)"
        else:
            for item in entry_data["items"]:
                if item["type"] == "node":
                    result += f"- [NODE] {item['path']}\n"
                else:
                    result += f"- [LEAF] {item['path']}\n"
    else:
        result = f"Unknown entry type: {entry_data['type']}"

    return result


@tool
def read_memory_entry(context: "AgentContext", path: str) -> str:
    """Read a memory entry.

    Args:
        path: Path to the memory entry

    Returns:
        The memory entry content or a list of contained memory paths if it's a directory,
        indicating whether each path is a node (directory) or leaf (entry)
    """
    result = context.memory_manager.read_entry(path)
    return _format_entry_as_markdown(result)


def _format_write_result_as_markdown(result: Dict[str, Any]) -> str:
    """Format a write operation result as markdown.

    Args:
        result: The structured result data

    Returns:
        A markdown-formatted string representation
    """
    if not result["success"]:
        return f"Error: {result['error']}"
    return result["message"]


@tool
def write_memory_entry(context: "AgentContext", path: str, content: str) -> str:
    """Write a memory entry.

    Args:
        path: Path to the memory entry
        content: Content to write
    """
    result = context.memory_manager.write_entry(path, content)
    return _format_write_result_as_markdown(result)


@tool
async def critique_memory(context: "AgentContext", prefix: str | None = None) -> str:
    """Generate a critique of the current memory organization.

    This tool analyzes the current memory structure and provides recommendations
    for improving organization, reducing redundancy, and identifying gaps.
    """
    # First get the tree structure for organization analysis
    tree_result = context.memory_manager.get_tree(prefix, -1)  # Get full tree

    if not tree_result["success"]:
        return f"Error getting memory tree: {tree_result['error']}"

    tree = tree_result["items"]

    # Get all memory entries for content analysis
    memory_files = list(context.memory_manager.base_dir.glob("**/*.md"))
    if not memory_files:
        return "No memory entries found to critique."

    # Build memory structure list showing paths without content
    memory_structure = []
    for file in memory_files:
        try:
            # Skip metadata files
            if ".metadata." in file.name:
                continue
            relative_path = file.relative_to(context.memory_manager.base_dir)
            # Strip .md extension for display
            memory_structure.append(str(relative_path).replace(".md", ""))
        except Exception as e:
            print(f"Error processing memory file {file}: {e}")

    system_prompt = """You are a memory organization expert. Your task is to analyze 
            the current organization of memory entries and provide constructive feedback.

            Focus on:
            1. Identifying redundancies or duplications in the structure
            2. Suggesting better organization or hierarchies
            3. Pointing out inconsistencies in naming or categorization
            4. Recommending consolidation where appropriate
            5. Identifying gaps in knowledge or categories that should be created

            Be specific and actionable in your recommendations."""

    user_prompt = f"""
            Here is the current memory organization tree:
            
            {json.dumps(tree, indent=2)}
            
            Here are all the memory entry paths:
            
            {json.dumps(memory_structure, indent=2)}
            
            Please analyze this memory organization and provide:

            1. An overall assessment of the current organization
            2. Specific issues you've identified in the structure
            3. Concrete recommendations for improving the organization
            4. Suggestions for any new categories that should be created
            """

    try:
        result = await agent(
            context=context,
            prompt=system_prompt + "\n\n" + user_prompt,
            model="smart",  # Use light model as specified
        )
        return result
    except Exception as e:
        return f"Error generating critique: {str(e)}"


@tool
def delete_memory_entry(context: "AgentContext", path: str) -> str:
    """Delete a memory entry.

    Args:
        path: Path to the memory entry to delete

    Returns:
        Status message indicating success or failure
    """
    result = context.memory_manager.delete_entry(path)
    if not result["success"]:
        return f"Error: {result['error']}"
    return result["message"]
