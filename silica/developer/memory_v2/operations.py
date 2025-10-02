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


def create_split_toolbox(storage: MemoryStorage) -> list:
    """
    Create a specialized toolbox for the split_memory agent.

    This toolbox provides direct storage access (no agentic operations)
    to avoid recursive AI calls during splitting. The tools are internal
    and not exposed to the main agent.

    Args:
        storage: Storage backend to use

    Returns:
        List of tool functions with closures over storage:
        - _memory_read: Direct read from storage
        - _memory_write: Direct write to storage (no merging)
        - _memory_list: List all memory paths

    Example:
        >>> tools = create_split_toolbox(storage)
        >>> # Use in sub-agent by passing tool names
        >>> tool_names = [t.__name__ for t in tools]
        >>> run_agent(context, prompt, tool_names=tool_names, ...)
    """
    # Import here to avoid circular imports
    from silica.developer.tools.framework import tool

    # Define internal tools with closure over storage
    @tool
    def _memory_read(context: "AgentContext", path: str) -> str:
        """
        Internal: Read memory content directly from storage.

        This is a direct read operation (no agentic processing).
        Used by split agent to explore memory structure.

        Args:
            path: Memory path to read (empty string for root)

        Returns:
            Formatted string with content and metadata
        """
        try:
            content = storage.read(path)
            size = len(content)
            path_display = path if path else "(root)"
            return f"Content at '{path_display}' ({size} bytes):\n```\n{content}\n```"
        except Exception as e:
            return f"Error reading '{path}': {e}"

    @tool
    def _memory_write(context: "AgentContext", path: str, content: str) -> str:
        """
        Internal: Write content directly to storage.

        This is a direct write operation (no agentic merging).
        Used by split agent to create child nodes.

        Args:
            path: Memory path to write to (empty string for root)
            content: Content to write

        Returns:
            Success or error message
        """
        try:
            storage.write(path, content)
            size = storage.get_size(path)
            path_display = path if path else "(root)"
            return f"✅ Successfully written to '{path_display}' ({size} bytes)"
        except Exception as e:
            return f"❌ Error writing to '{path}': {e}"

    @tool
    def _memory_list(context: "AgentContext") -> str:
        """
        Internal: List all memory paths in storage.

        This is a direct list operation.
        Used by split agent to see existing structure.

        Returns:
            Formatted list of all memory paths with sizes
        """
        try:
            paths = storage.list_files()
            if not paths:
                return "No memory files exist yet."

            result = "Existing memory paths:\n"
            for p in sorted(paths):
                try:
                    size = storage.get_size(p)
                    path_display = p if p else "(root)"
                    result += f"  - '{path_display}' ({size} bytes)\n"
                except Exception:
                    result += f"  - '{p}' (size unknown)\n"
            return result
        except Exception as e:
            return f"Error listing paths: {e}"

    # Return list of tools
    return [_memory_read, _memory_write, _memory_list]


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

**Current content at '{path or "(root)"}'** ({len(existing_content)} bytes):
```
{existing_content}
```

**New content to incorporate**:
```
{new_content}
```

**Your task**: {instruction}

**Critical Guidelines - Focus on Conciseness**:

**What to Keep**:
- Generalizable facts, patterns, and learnings
- Architectural decisions and their reasoning
- Best practices and insights that remain relevant
- Key relationships and dependencies
- Timeless technical knowledge

**What to Discard or Summarize**:
- Temporary project statuses (unless they reveal lasting insights)
- Specific dates and version numbers (unless historically significant)
- Detailed logs of completed work
- Redundant information already well-covered
- Information superseded by newer understanding

**How to Merge**:
1. **Synthesize, don't append**: Look for higher-level patterns across old + new content
2. **Consolidate redundancy**: If similar info appears multiple times, create one better statement
3. **Update stale info**: Replace outdated facts with current understanding
4. **Preserve wisdom**: Keep insights and learnings that have lasting value
5. **Stay concise**: Aim to keep or reduce total length when possible

**Goal**: The merged content should be MORE valuable but NOT necessarily longer.
Think: "What would I want to remember a year from now?" Not: "What happened this week?"

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
- Focus on generalizable facts, patterns, and learnings (not temporary statuses)
- Use clear markdown formatting (headings, lists, code blocks as appropriate)
- Organize the information logically
- Keep it concise but complete - aim for lasting value
- Extract the essence and insights, not exhaustive details
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

        split_prompt = f"""You are reorganizing a large memory file by splitting it into focused, semantic child files.

**Why we're splitting**: This file has grown to {size} bytes ({size/1024:.2f} KB), making it harder to navigate and maintain.

**Your goal**: Create a cleaner, more navigable structure while maintaining (or improving) content quality.

**Current content to split**:
```markdown
{content}
```

**STEP 1: Analyze and Plan**

Review the content and identify:
1. **Natural groupings**: What are the 3-5 major themes/topics?
2. **Semantic categories**: What names would make these groups immediately clear?
3. **Hierarchy**: What insights belong at the parent level vs in children?
4. **Consolidation opportunities**: Where can you reduce redundancy during the split?

**Good child names**: `core_architecture`, `learnings`, `best_practices`, `technical_decisions`
**Avoid**: `misc`, `other`, `temp`, overly specific names like `bug_fixes_jan_2025`

**STEP 2: Create Child Files** 

For EACH semantic group, call _memory_write:
```python
_memory_write(
    path="{parent_path}/child_name",
    content="[Child content - focus on that specific theme]"
)
```

Note: _memory_write does direct writes (no AI merging), so format content clearly.

**Child content guidelines**:
- Stay focused on the child's theme
- Maintain our conciseness philosophy (insights over details)
- Each child should feel cohesive and purposeful
- Remove redundancy within each child during the split

**STEP 3: Create a Valuable Parent**

The parent should be an **executive summary + navigation hub**, not just a table of contents.

Call _memory_write for the parent path with content structured like:

```markdown
# [Parent Title]

[2-3 sentence overview of what this memory area covers and why it matters]

## Key Insights

[3-5 bullet points of the MOST important cross-cutting insights - things that 
tie themes together or represent the highest-level learnings. These shouldn't 
just duplicate what's in children; they should provide context and connections.]

- Insight 1: [Something that spans multiple children or provides meta-context]
- Insight 2: [A pattern or principle that emerges from the details]
- Insight 3: [Critical context for understanding the children]

## Organization

This memory is organized into focused areas:

- **[Child Name](child_name)**: [What's in it and when to look there]
- **[Child Name](child_name)**: [What's in it and when to look there]
- **[Child Name](child_name)**: [What's in it and when to look there]

[Optional: Brief note about relationships between children or how they fit together]
```

**CRITICAL PRINCIPLES:**

1. **Preserve all valuable content** - But use the split as an opportunity to consolidate redundancy
2. **Parent = Context + Navigation** - Not just a table of contents; provide insights and connections
3. **Children = Focused themes** - Each child should have a clear, singular purpose
4. **Semantic names** - Names should make content discoverable and obvious
5. **Conciseness throughout** - This is reorganization, not just redistribution
6. **Use markdown links** - Format: `[Display Text](relative/path)`

**Example of a GOOD parent** (note the valuable insights, not just links):

```markdown
# Software Development Learnings

Core insights and best practices accumulated from building production systems 
in Python, TypeScript, and infrastructure automation.

## Key Insights

- **Architecture evolution**: Start simple, add complexity only when validated by real need
- **Testing pyramid**: Unit tests for logic, integration tests for workflows, e2e for critical paths
- **Prompt engineering matters more than framework choice** for AI-powered tools

## Organization

- **[Python Patterns](python_patterns)**: Language-specific best practices, async patterns, type hints
- **[System Design](system_design)**: Architectural decisions, scalability learnings, trade-offs
- **[Developer Experience](developer_experience)**: Tooling choices, workflow optimizations, productivity insights

These areas are interconnected - good architecture enables good testing, which improves DX.
```

**Example of a POOR parent** (just a table of contents):

```markdown
# Memory

Contents:
- [Projects](projects) - Projects
- [Knowledge](knowledge) - Knowledge  
- [Notes](notes) - Notes
```

**Now execute the split:**
1. Call _memory_write for each child (with focused, consolidated content)
2. Call _memory_write for the parent (with insights + navigation)
3. Ensure all valuable information is preserved (but consolidated where redundant)"""

        # Create specialized toolbox with direct storage access
        tools = create_split_toolbox(storage)

        # Run sub-agent with internal memory tools (direct storage access, no agentic operations)
        _ = await run_agent(
            context=context,
            prompt=split_prompt,
            tools=tools,  # Pass actual tool objects, not names
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
