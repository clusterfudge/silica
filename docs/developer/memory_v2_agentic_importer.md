# Memory V2 Agentic Importer

## Overview

The Memory V2 migration system has been redesigned to use fully agentic import, where the AI agent is responsible for:
1. **Extracting** salient information from V1 files (not dumping entire files)
2. **Deciding** where to place the extracted information in the V2 memory hierarchy
3. **Integrating** the information intelligently using `write_memory_agentic`

This approach aligns with the Memory V2 philosophy of organic growth and intelligent content management.

## Key Changes

### Before (Direct Import)

The old approach:
- Called `extract_information_from_file()` to get extracted content as a string
- Always wrote to root (`""`) using `agentic_write()`
- Agent had no control over placement decisions
- Result: Everything piled up in root memory

### After (Fully Agentic Import)

The new approach:
- `extract_and_store_v1_file()` is a single function that does both extraction AND storage
- Agent receives the V1 file content along with current V2 structure
- Agent has access to tools: `write_memory_agentic`, `read_memory`, `list_memory_files`
- Agent decides:
  - What information is worth extracting
  - Where in the V2 hierarchy to place it
  - How to integrate with existing content

## Implementation Details

### Function Signature

```python
async def extract_and_store_v1_file(
    v1_file: V1MemoryFile,
    storage: MemoryStorage,
    context: AgentContext
) -> tuple[bool, str]:
    """
    Extract salient information from a V1 file and intelligently store it in V2.
    
    Returns:
        Tuple of (success: bool, message: str)
    """
```

### Agent Prompt Structure

The agent receives a comprehensive prompt with two main sections:

#### Step 1: Extract Salient Information

Guides the agent to:
- ✅ Extract key facts, best practices, project states, important relationships
- ❌ Avoid redundant, trivial, outdated, or verbose information
- Output a structured format: Type, Topic, Summary, Key Facts, Context, Related

#### Step 2: Store in the Right Place

The agent:
- Views the current V2 memory structure (existing paths and root content)
- Calls `write_memory_agentic` with:
  - `content`: The extracted, structured information
  - `path`: Semantic location (e.g., "projects", "knowledge", "")
  - `instruction`: How to integrate with existing content

### What Gets Extracted

**✅ DO Extract:**
- Key facts about individuals, projects, companies, technologies
- Current project states, statuses, and recent decisions
- Best practices, learnings, and insights
- Technical details that are reference-worthy (APIs, configs, architectures)
- Important relationships and connections
- Actionable information and context

**❌ DON'T Extract:**
- Redundant information already in V2
- Trivial details (meeting schedules, old status updates)
- Outdated information superseded by newer facts
- Verbose logs or repetitive content
- Information that provides no future value

### Example: Silica Project Architecture

**V1 File Content (500 lines):**
```markdown
# Silica Project

[... 500 lines of detailed content, meeting notes, old status updates, etc ...]

## Architecture
Memory V2 uses organic growth with single root file...
Storage abstraction supports local disk and S3...
Agentic operations for write, search, split...

[... more content ...]
```

**Agent Extracts (Concise):**
```markdown
Type: project/technical-reference
Topic: Silica Memory V2 Architecture

Summary: V2 uses organic growth pattern with single root file 
that splits at 10KB threshold.

Key Facts:
- Starts with single 'memory' file, grows through AI-driven splitting
- Storage abstraction supports local disk and S3 backends
- Agentic operations for write (merge), search (traverse), and split
- Each node can have both content and children

Context: Core architecture for memory system redesign completed Jan 2025
```

**Agent Stores:**
```python
write_memory_agentic(
    content="[extracted content above]",
    path="projects",  # Agent chose semantic location
    instruction="This is Silica project architecture info from V1 migration. 
                 If there's existing Silica content, merge with it."
)
```

## Benefits

1. **Quality Over Quantity**
   - Only valuable information makes it to V2
   - No bloat from verbose V1 files

2. **Intelligent Placement**
   - Content goes to semantically appropriate locations
   - Agent considers existing V2 structure
   - Natural organization emerges

3. **Smart Integration**
   - `write_memory_agentic` handles merging with existing content
   - Avoids duplication automatically
   - Maintains context and relationships

4. **Flexible and Extensible**
   - Agent can create new semantic paths as needed
   - Adapts to evolving V2 structure
   - No hardcoded rules or paths

5. **Aligned with Memory V2 Philosophy**
   - Organic growth from intelligent decisions
   - Agentic operations throughout
   - Content quality driven by AI judgment

## Testing

The new approach is thoroughly tested:

### Unit Tests (`test_memory_v2_migration.py`)
- 22 tests covering scanning, state management, metadata loading
- Tests for V1 file structure, migration state persistence
- Integration tests for resumable processing

### Agentic Tests (`test_memory_v2_migration_agentic.py`)
- 6 tests specifically for agentic import behavior
- Verifies agent has correct tools (`write_memory_agentic`, `read_memory`, `list_memory_files`)
- Validates prompt emphasizes summarization over dumping
- Confirms V2 context is provided for placement decisions
- Tests error handling and content loading

All 28 tests pass ✅

## Usage

### CLI Command

```bash
# Test migration with first 10 files
silica memory-v2 migrate --max-files 10

# Full migration to default persona
silica memory-v2 migrate

# Migrate to specific persona  
silica memory-v2 migrate --persona coding_agent

# Resume from last checkpoint (default behavior)
silica memory-v2 migrate

# Start fresh (ignore progress)
silica memory-v2 migrate --no-resume
```

### Programmatic Usage

```python
from silica.developer.memory_v2.migration import extract_and_store_v1_file
from silica.developer.memory_v2.storage import LocalDiskStorage
from silica.developer.context import AgentContext

# Setup
storage = LocalDiskStorage("/path/to/memory_v2")
context = AgentContext.create(...)

# Process a V1 file
success, message = await extract_and_store_v1_file(
    v1_file=my_v1_file,
    storage=storage,
    context=context
)

if success:
    print(f"✅ Successfully migrated: {message}")
else:
    print(f"❌ Failed: {message}")
```

## Implementation Files

- **`silica/developer/memory_v2/migration.py`**
  - `extract_and_store_v1_file()` - Main agentic import function
  - Migration state management
  - V1 scanning and metadata loading

- **`silica/developer/memory_v2/cli.py`**
  - `migrate` command implementation
  - Progress tracking and cost reporting
  - State persistence for resumability

- **`silica/developer/memory_v2/operations.py`**
  - `agentic_write()` - Intelligent content merging
  - Used by migration agent via `write_memory_agentic` tool

- **`silica/developer/tools/memory_v2_tools.py`**
  - `write_memory_agentic` - Tool wrapper for agentic writes
  - `read_memory`, `list_memory_files` - Tools for agent exploration

## Future Enhancements

1. **Chunking for Large Files**
   - Process very large V1 files in chunks
   - Avoid token limit issues with huge files

2. **Smart Deduplication**
   - Detect when multiple V1 files contain same information
   - Extract common information once

3. **Relationship Preservation**
   - Track V1 file relationships (backlinks, etc.)
   - Maintain those relationships in V2

4. **Incremental Migration**
   - Allow selective file migration
   - Skip certain V1 paths or patterns

5. **Migration Analytics**
   - Report on what was extracted vs discarded
   - Show organization decisions made by agent

## References

- Memory V2 Specification: `docs/developer/memory_v2_spec.md`
- GitHub Issue: https://github.com/clusterfudge/silica/issues/40
- Agentic Operations: `silica/developer/memory_v2/operations.py`
- Memory V2 Tools: `silica/developer/tools/memory_v2_tools.py`
