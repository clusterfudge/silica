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
    Write content to memory using AI to intelligently merge with existing content.

    This is the core write operation for Memory V2. It:
    1. Reads existing content at the specified path (if any)
    2. Uses AI to merge new content with existing content
    3. Writes the merged result back
    4. Checks if file size exceeds thresholds

    The AI agent:
    - Identifies duplicate information and avoids redundancy
    - Updates outdated information with newer details
    - Maintains logical organization and structure
    - Preserves important context
    - Creates coherent, well-organized content

    Args:
        storage: Storage backend to use
        path: Path where content should be written (typically "" for root)
        new_content: New information to incorporate
        context: AgentContext for AI operations (required for intelligent merging)
        instruction: Custom instruction for how to incorporate content

    Returns:
        WriteResult with operation details
    """
    # If no context, fall back to simple append
    if context is None:
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

    # Use AI to intelligently merge content
    from silica.developer.tools.subagent import run_agent

    # Read existing content
    existing_content = ""
    if storage.exists(path):
        try:
            existing_content = storage.read(path)
        except Exception:
            existing_content = ""

    # Prepare merge prompt
    if existing_content:
        merge_prompt = f"""You are updating a memory file with new information.

**Current content at '{path or "(root)"}'**:
```
{existing_content}
```

**New content to incorporate**:
```
{new_content}
```

**Your task**: {instruction}

**Guidelines**:
- Avoid duplicating information that's already present
- Update outdated information with newer details
- Maintain or improve the logical organization
- Preserve important context and relationships
- Keep the content concise and well-structured
- If the new content is already covered, you may skip adding it
- Use clear markdown formatting (headings, lists, code blocks as appropriate)

**Output**: Provide ONLY the final merged content. Do not include any commentary, just the content itself.
"""
    else:
        # No existing content - just format the new content nicely
        merge_prompt = f"""You are creating a new memory file.

**Content to store**:
```
{new_content}
```

**Your task**: Format this content clearly and concisely for storage.

**Guidelines**:
- Use clear markdown formatting (headings, lists, code blocks as appropriate)
- Organize the information logically
- Keep it concise but complete
- No commentary, just the formatted content

**Output**: Provide ONLY the formatted content. No commentary.
"""

    try:
        # Run sub-agent to merge content
        result = await run_agent(
            context=context,
            prompt=merge_prompt,
            tool_names=[],  # No tools needed, just text processing
            system=None,
            model="smart",  # Use smart model for quality merging
        )

        # The result is the merged content
        merged_content = result.strip() if result else new_content

        # Write merged content
        storage.write(path, merged_content)
        size = storage.get_size(path)

        return WriteResult(
            success=True,
            path=path,
            size_bytes=size,
            split_triggered=(size > SIZE_THRESHOLD),
        )

    except Exception:
        # Fall back to simple append on error
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

    Looks for markdown link syntax [text](path) in the content.

    Args:
        content: Content to search for links

    Returns:
        List of linked paths
    """
    # Match markdown link syntax: [text](path)
    # This will capture the path part from [any text](path/to/file)
    pattern = r"\[([^\]]+)\]\(([^)]+)\)"
    matches = re.findall(pattern, content)
    # Return just the paths (second capture group)
    return [path for text, path in matches]


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

        # Get list of files before split
        files_before = set(storage.list_files())

        # Use sub-agent for intelligent splitting
        from silica.developer.tools.subagent import run_agent

        # Parent path for child nodes
        parent_path = path if path else ""

        split_prompt = f"""You are splitting a large memory file into smaller, focused child files.

**Parent path**: `{parent_path or "(root)"}` 
**File size**: {size} bytes ({size/1024:.2f} KB) - exceeds 10 KB threshold
**Split strategy**: Create 3-5 focused child files organized by topic/theme

**Current content to split**:
```markdown
{content}
```

**Your task - Complete ALL steps:**

**Step 1: Plan the split**
- Identify 3-5 major themes/topics in the content
- Choose clear, semantic child names (e.g., "projects", "knowledge", "meetings", etc.)
- Decide which content goes to each child

**Step 2: Create each child file**
For EACH child you identified, call write_memory with:
- path: "{parent_path}/child_name" (use the parent path as prefix)
- content: The full content for that child (be thorough!)

**Step 3: Update the parent file**
Call write_memory for path "{parent_path or '(empty string for root)'}" with content that includes:

1. **High-level overview** - Brief summary of what this memory area contains (2-3 sentences)
2. **Key highlights** - Important top-level information that shouldn't be buried in children (3-5 bullet points of the most important facts)
3. **Organization** - Brief explanation of how the content is organized
4. **Markdown links to children** in a "## Contents" section:
   ```markdown
   ## Contents
   
   - [Projects](projects) - Description of what's in projects
   - [Knowledge](knowledge) - Description of what's in knowledge
   - [Meetings](meetings) - Description of what's in meetings
   ```

**CRITICAL GUIDELINES:**
- **Preserve ALL content** - Every piece of information must go somewhere (either parent or a child)
- **Call write_memory for EACH child** - Don't just mention them, actually create them!
- **Use markdown links** - Format: `[Display Text](relative/path)` NOT `[[path]]`
- **Keep parent valuable** - It should provide context and orientation, not just be a table of contents
- **Use semantic names** - Names should clearly indicate what's inside
- **No data loss** - If in doubt, include more context in the parent

**Example parent structure:**
```markdown
# Project Memory

This is my personal project knowledge base, containing information about active and completed software projects, technical learnings, and development notes accumulated since 2024.

**Key Highlights:**
- Currently working on 3 active projects: Silica (AI agent framework), WebApp (personal site), and CLI tools
- Primary tech stack: Python 3.11+, TypeScript, React
- All projects follow test-driven development with >80% coverage

**Organization:**
I've organized this memory into focused areas for easier navigation and maintenance. Each section contains detailed information about that specific domain.

## Contents

- [Projects](projects) - Active and completed software projects with architecture docs
- [Knowledge Base](knowledge) - Technical learnings, patterns, and best practices
- [Meeting Notes](meetings) - Important discussions and decisions from team meetings
- [Ideas](ideas) - Future project ideas and technical explorations

Last updated: 2025-01-02
```

**Now execute the split:** Call write_memory for each child file, then update the parent."""

        # Run sub-agent with write_memory tool
        _ = await run_agent(
            context=context,
            prompt=split_prompt,
            tool_names=["write_memory"],
            system=None,
            model="smart",  # Use smart model for complex reasoning
        )

        # Get the new file list to determine what was created
        files_after = set(storage.list_files())
        new_children = sorted(files_after - files_before)

        # Verify at least some children were created
        if not new_children:
            # Split failed - no children created
            return WriteResult(
                success=False,
                path=path,
                size_bytes=size,
                split_triggered=False,
                new_files=[],
            )

        # Get updated parent size
        final_size = storage.get_size(path) if storage.exists(path) else 0

        return WriteResult(
            success=True,
            path=path,
            size_bytes=final_size,
            split_triggered=False,  # Split already happened
            new_files=new_children,
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
3. Look for markdown links `[text](path)` in the content that might lead to relevant information
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
- Follow markdown links `[text](path)` that appear promising
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
