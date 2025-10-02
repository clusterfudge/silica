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


async def agentic_write(
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
        context: AgentContext for sub-agent execution (required for agent mode)
        instruction: Custom instruction for how to incorporate content

    Returns:
        WriteResult with operation details
    """
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

        # If context not provided, fall back to simple merge
        if context is None:
            merged_content = f"{existing_content}\n\n---\n\n{new_content}"
            storage.write(path, merged_content)
            size = storage.get_size(path)
            return WriteResult(
                success=True,
                path=path,
                size_bytes=size,
                split_triggered=(size > SIZE_THRESHOLD),
            )

        # Use sub-agent for intelligent merging
        from silica.developer.tools.subagent import run_agent

        merge_prompt = f"""You are updating a memory file with new information.

**Current file path**: {path}

**Existing content**:
```
{existing_content}
```

**New information to incorporate**:
```
{new_content}
```

**Your task**: {instruction}

Guidelines:
1. Avoid duplicating information that's already present
2. Update or replace outdated information with newer details
3. Maintain logical organization and structure
4. Preserve important context and details from existing content
5. Use clear markdown formatting
6. If the new information conflicts with existing, prefer the new information
7. Merge related topics together rather than keeping them separate

Write the final merged content that incorporates both existing and new information.
Output ONLY the final merged content, no explanations or meta-commentary.
"""

        # Run sub-agent for intelligent merging
        merged_content = await run_agent(
            context=context,
            prompt=merge_prompt,
            tool_names=[],  # No tools needed - just text processing
            system=None,
            model="smart",  # Use smart model for better reasoning
        )

        # Write the merged content
        storage.write(path, merged_content)
        size = storage.get_size(path)

        return WriteResult(
            success=True,
            path=path,
            size_bytes=size,
            split_triggered=(size > SIZE_THRESHOLD),
        )

    except Exception:
        # Fall back to simple merge on error
        try:
            existing = storage.read(path) if storage.exists(path) else ""
            merged = f"{existing}\n\n---\n\n{new_content}" if existing else new_content
            storage.write(path, merged)
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


async def split_memory_node(
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
        context: AgentContext for sub-agent execution (required for agent mode)

    Returns:
        WriteResult with details of created child nodes
    """
    try:
        # Check if file exists
        if not storage.exists(path):
            return WriteResult(
                success=False,
                path=path,
                size_bytes=0,
                split_triggered=False,
            )

        # Read content and check size
        content = storage.read(path)
        size = storage.get_size(path)

        # If no context, can't use agent
        if context is None:
            return WriteResult(
                success=False,
                path=path,
                size_bytes=size,
                split_triggered=False,
            )

        # Use sub-agent for intelligent splitting
        from silica.developer.tools.subagent import run_agent

        split_prompt = f"""You are analyzing a memory file that needs to be split into smaller, organized child nodes.

**File path**: {path}
**File size**: {size} bytes ({size/1024:.2f} KB)
**Threshold**: 10 KB

**Current content**:
```
{content}
```

**Your task**:
1. Analyze the content and identify natural groupings (topics, entities, themes, time periods)
2. Choose an appropriate split strategy:
   - **Topic-based**: Group by semantic topics (e.g., "projects", "knowledge", "notes")
   - **Entity-based**: Group by entities (e.g., "silica", "webapp", specific projects)
   - **Chronological**: Group by time periods (for logs/journals)
   - **Category-based**: Group by categories (e.g., "python", "javascript", "devops")

3. Create child nodes with clear, semantic names (e.g., "{path}/projects", "{path}/knowledge")
4. Distribute the content to appropriate child nodes
5. Update the parent node ({path}) with:
   - A high-level summary
   - Links to children using [[child/path]] syntax in a ## Links section
   - Any content that doesn't fit child categories

Guidelines:
- Use clear, semantic names for children (no generic names like "node1" or "part1")
- Each child should be a cohesive, focused unit
- Parent should remain useful as an overview/routing document
- Preserve ALL information (no data loss!)
- Use markdown formatting consistently
- Add ## Links section in parent for navigation

Execute the split by using these tools:
1. Use write_memory to create each child node with its content
2. Use write_memory to update the parent with summary and links

You have access to: write_memory
"""

        # Run sub-agent with write_memory tool
        _ = await run_agent(
            context=context,
            prompt=split_prompt,
            tool_names=["write_memory"],
            system=None,
            model="smart",  # Use smart model for complex reasoning
        )

        # Get the new file list to determine what was created
        all_files_after = set(storage.list_files())

        # Find child nodes (files under the parent path)
        new_children = [
            f for f in all_files_after if f.startswith(f"{path}/") and f != path
        ]

        # Get updated parent size
        final_size = storage.get_size(path) if storage.exists(path) else 0

        return WriteResult(
            success=True,
            path=path,
            size_bytes=final_size,
            split_triggered=False,  # Split already happened
            new_files=sorted(new_children),
        )

    except Exception:
        # Return failure result
        size = storage.get_size(path) if storage.exists(path) else 0
        return WriteResult(
            success=False,
            path=path,
            size_bytes=size,
            split_triggered=False,
        )


async def search_memory(
    storage: MemoryStorage,
    query: str,
    max_results: int = 10,
    start_path: str = "memory",
    context: Optional[AgentContext] = None,
) -> List[SearchResult]:
    """
    Search memory using agent-driven traversal or simple text search.

    The agent will:
    - Start at the specified path
    - Read and assess relevance
    - Follow promising links using [[path]] syntax
    - Collect relevant excerpts
    - Track visited paths to avoid loops
    - Return semantically ranked results

    Args:
        storage: Storage backend to use
        query: Search query
        max_results: Maximum number of results to return
        start_path: Path to start search from
        context: AgentContext for sub-agent execution (optional, falls back to text search)

    Returns:
        List of SearchResult objects
    """
    # If no context, fall back to simple text search
    if context is None:
        return _simple_text_search(storage, query, max_results)

    try:
        # Get list of available files for the agent to know the structure
        available_paths = storage.list_files()

        # Use sub-agent for intelligent search with link traversal
        from silica.developer.tools.subagent import run_agent

        search_prompt = f"""You are searching through a hierarchical memory system for: "{query}"

**Starting path**: {start_path}
**Maximum results**: {max_results}
**Available memory paths**: {', '.join(available_paths[:20])}{'...' if len(available_paths) > 20 else ''}

**Your approach:**
1. Start by reading the content at the starting path
2. Assess if the content is relevant to the query
3. Look for [[path]] links in the content that might lead to relevant information
4. Follow the most promising links by reading those paths
5. Track which paths you've visited to avoid loops
6. Collect relevant excerpts with their paths
7. Continue until you have {max_results} results or have explored all promising paths

**Tools available:**
- read_memory: Read content from a memory path
- list_memory_files: See what paths exist

**Output format:**
For each relevant result, output exactly in this format:
```
RESULT
PATH: <path>
RELEVANCE: <score between 0.0 and 1.0>
EXCERPT: <relevant excerpt from the content>
CONTEXT: <brief explanation of why this is relevant and how you found it>
---
```

**Guidelines:**
- Prioritize paths that seem semantically related to the query
- Follow [[links]] that appear promising
- Higher relevance scores (closer to 1.0) for exact matches and highly relevant content
- Lower relevance scores (0.3-0.6) for tangentially related content
- Keep excerpts concise (50-150 characters) and informative
- Provide context about the path taken to find the result
- Stop when you have {max_results} results or no more promising paths

Begin your search now. Output only the RESULT blocks, no other commentary.
"""

        # Run sub-agent with memory tools
        agent_output = await run_agent(
            context=context,
            prompt=search_prompt,
            tool_names=["read_memory", "list_memory_files"],
            system=None,
            model="smart",  # Use smart model for reasoning
        )

        # Parse the agent's output into SearchResult objects
        results = _parse_search_results(agent_output)

        # Sort by relevance and limit to max_results
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:max_results]

    except Exception:
        # Fall back to simple text search on error
        return _simple_text_search(storage, query, max_results)


def _simple_text_search(
    storage: MemoryStorage,
    query: str,
    max_results: int,
) -> List[SearchResult]:
    """
    Simple text-based search across all files.
    Used as fallback when agent search is not available or fails.
    """
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
                            context=f"Found in {file_path} (text search)",
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


def _parse_search_results(agent_output: str) -> List[SearchResult]:
    """
    Parse the agent's search output into SearchResult objects.

    Expected format:
    RESULT
    PATH: path/to/file
    RELEVANCE: 0.85
    EXCERPT: excerpt text here
    CONTEXT: context about the result
    ---
    """
    results = []

    # Split by "RESULT" markers
    blocks = agent_output.split("RESULT")

    for block in blocks:
        if not block.strip():
            continue

        try:
            # Extract fields using simple parsing
            lines = [line.strip() for line in block.strip().split("\n") if line.strip()]

            path = None
            relevance = 0.5
            excerpt = ""
            context = ""

            for line in lines:
                if line.startswith("PATH:"):
                    path = line[5:].strip()
                elif line.startswith("RELEVANCE:"):
                    try:
                        relevance = float(line[10:].strip())
                    except ValueError:
                        relevance = 0.5
                elif line.startswith("EXCERPT:"):
                    excerpt = line[8:].strip()
                elif line.startswith("CONTEXT:"):
                    context = line[8:].strip()
                elif line == "---":
                    break

            # Only add if we have at least a path
            if path:
                results.append(
                    SearchResult(
                        path=path,
                        excerpt=excerpt or f"Content from {path}",
                        relevance_score=max(0.0, min(1.0, relevance)),
                        context=context or f"Found in {path}",
                    )
                )

        except Exception:
            # Skip malformed blocks
            continue

    return results
