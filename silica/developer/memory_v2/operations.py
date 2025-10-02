"""
Agentic operations for Memory V2 system.

This module provides intelligent agent-driven operations for writing,
splitting, and searching memory content.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from silica.developer.context import AgentContext
from silica.developer.memory_v2.storage import MemoryStorage


@dataclass
class WriteResult:
    """Result of a write operation."""

    success: bool
    path: str
    size_bytes: int
    split_triggered: bool = False
    new_files: List[str] = None

    def __post_init__(self):
        if self.new_files is None:
            self.new_files = []


@dataclass
class SearchResult:
    """Result of a search operation."""

    path: str
    excerpt: str
    relevance_score: float
    context: str = ""


# Constants
SIZE_THRESHOLD = 10240  # 10KB
SIZE_WARNING = 8192  # 8KB (80% of threshold)


def agentic_write(
    storage: MemoryStorage,
    path: str,
    new_content: str,
    context: Optional[AgentContext] = None,
    instruction: str = "Incorporate the new information into the existing content intelligently.",
) -> WriteResult:
    """
    Write content to memory using an agent to intelligently merge with existing content.

    The agent will:
    - Read existing content (if any)
    - Analyze both old and new content
    - Merge information to avoid duplication
    - Maintain logical structure and organization
    - Update outdated information
    - Preserve important context

    Args:
        storage: Storage backend to use
        path: Path to write to
        new_content: New information to incorporate
        context: AgentContext for sub-agent execution
        instruction: Custom instruction for how to incorporate content

    Returns:
        WriteResult with operation details
    """
    # For now, implement a simple merge strategy
    # TODO: Use sub-agent for intelligent merging
    try:
        # Check if file exists
        existing_content = ""
        if storage.exists(path):
            existing_content = storage.read(path)

        # If no existing content, just write new content
        if not existing_content:
            storage.write(path, new_content)
            size = storage.get_size(path)
            return WriteResult(
                success=True,
                path=path,
                size_bytes=size,
                split_triggered=(size > SIZE_THRESHOLD),
            )

        # Simple merge: append new content with separator
        # TODO: Replace with agent-driven intelligent merge
        merged_content = f"{existing_content}\n\n---\n\n{new_content}"
        storage.write(path, merged_content)
        size = storage.get_size(path)

        return WriteResult(
            success=True,
            path=path,
            size_bytes=size,
            split_triggered=(size > SIZE_THRESHOLD),
        )

    except Exception:
        return WriteResult(
            success=False,
            path=path,
            size_bytes=0,
            split_triggered=False,
        )


def extract_links(content: str) -> List[str]:
    """
    Extract memory links from content.

    Looks for [[path]] syntax in the content.

    Args:
        content: Content to search for links

    Returns:
        List of linked paths
    """
    # Match [[path]] syntax
    pattern = r"\[\[([^\]]+)\]\]"
    matches = re.findall(pattern, content)
    return matches


def split_memory_node(
    storage: MemoryStorage,
    path: str,
    context: Optional[AgentContext] = None,
) -> WriteResult:
    """
    Split a large memory node into smaller child nodes.

    The agent will:
    - Analyze content to identify natural groupings
    - Create child nodes with semantic names
    - Distribute content to appropriate children
    - Update parent with summary and links

    Args:
        storage: Storage backend to use
        path: Path to the node to split
        context: AgentContext for sub-agent execution

    Returns:
        WriteResult with details of created child nodes
    """
    # TODO: Implement agent-driven splitting
    # For now, return a placeholder result
    try:
        size = storage.get_size(path)
        return WriteResult(
            success=False,  # Not yet implemented
            path=path,
            size_bytes=size,
            split_triggered=False,
            new_files=[],
        )
    except Exception:
        return WriteResult(
            success=False,
            path=path,
            size_bytes=0,
            split_triggered=False,
        )


def search_memory(
    storage: MemoryStorage,
    query: str,
    max_results: int = 10,
    start_path: str = "memory",
    context: Optional[AgentContext] = None,
) -> List[SearchResult]:
    """
    Search memory using agent-driven traversal.

    The agent will:
    - Start at the specified path
    - Read and assess relevance
    - Follow promising links
    - Collect relevant excerpts
    - Return ranked results

    Args:
        storage: Storage backend to use
        query: Search query
        max_results: Maximum number of results to return
        start_path: Path to start search from
        context: AgentContext for sub-agent execution

    Returns:
        List of SearchResult objects
    """
    # TODO: Implement agent-driven search
    # For now, implement simple text search across all files
    results = []

    try:
        # Get all files
        all_paths = storage.list_files()

        # Search in each file
        for file_path in all_paths:
            try:
                content = storage.read(file_path)

                # Simple case-insensitive search
                if query.lower() in content.lower():
                    # Extract excerpt with some context
                    query_pos = content.lower().find(query.lower())
                    start = max(0, query_pos - 50)
                    end = min(len(content), query_pos + len(query) + 50)
                    excerpt = content[start:end].strip()

                    # Add ellipsis if truncated
                    if start > 0:
                        excerpt = "..." + excerpt
                    if end < len(content):
                        excerpt = excerpt + "..."

                    # Simple relevance scoring based on query frequency
                    count = content.lower().count(query.lower())
                    relevance = min(1.0, count * 0.2)

                    results.append(
                        SearchResult(
                            path=file_path,
                            excerpt=excerpt,
                            relevance_score=relevance,
                            context=f"Found in {file_path}",
                        )
                    )

                    if len(results) >= max_results:
                        break

            except Exception:
                # Skip files that can't be read
                continue

        # Sort by relevance
        results.sort(key=lambda r: r.relevance_score, reverse=True)

    except Exception:
        pass

    return results[:max_results]
