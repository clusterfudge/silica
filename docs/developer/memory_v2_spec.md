# Memory V2 Specification

## Overview

A radically simplified memory system that starts with a single file and organically grows through agentic splitting when files become too large.

## Core Concepts

### Single Entry Point
- All memory begins in a single file called `memory`
- This file serves as both the root content and the routing table
- No predetermined hierarchy or structure

### Organic Growth
- When a file exceeds 10KB, an agent analyzes the content and chooses an organization strategy
- The agent creates one or more new files based on semantic clustering
- The original file retains:
  - High-level context and summary
  - Routing information (links to child files)
  - Content that doesn't fit the split categories

### Agentic Operations
- **Write operations**: Agent reads entire file, incorporates new content, rewrites file
- **Search operations**: Agent traverses memory graph following semantic links
- **Split operations**: Agent determines optimal organization strategy

## File Format

### Memory File Structure

```markdown
# [Optional: Title/Topic]

[Main content of this memory node]

## Links

- [[path/to/child/file]] - Brief description of what's in this file
- [[another/path]] - Another topic area

## Metadata

last_updated: 2025-01-15T10:30:00Z
size_bytes: 8234
split_from: parent/path (optional)
```

### Naming Conventions

- Root file: `memory`
- Child files: Semantic names chosen by agent (e.g., `projects`, `python_knowledge`, `user_preferences`)
- Nested children: `parent_name/child_name` (e.g., `projects/silica`, `python_knowledge/async`)

## API Interface

### read_memory(path: Optional[str] = None) -> str

Read a memory file and return its contents.

**Parameters:**
- `path`: Optional path to a specific memory file. If None or empty, reads root `memory` file.

**Returns:**
- String content of the memory file

**Raises:**
- `MemoryNotFoundError`: If the specified path doesn't exist

**Example:**
```python
# Read root memory
content = read_memory()

# Read specific file
content = read_memory("projects/silica")
```

### write_memory(content: str, path: Optional[str] = None, mode: str = "update") -> WriteResult

Write to a memory file. Default behavior is to read existing content, incorporate new information, and rewrite.

**Parameters:**
- `content`: New information to incorporate
- `path`: Optional path to specific memory file. If None, writes to root `memory` file.
- `mode`: Write mode
  - `"update"` (default): Agent reads existing file, incorporates content, rewrites
  - `"append"`: Append to end of file (discouraged, only for performance-critical cases)
  - `"replace"`: Replace entire file content (use with caution)

**Returns:**
- `WriteResult` object containing:
  - `success`: bool
  - `path`: str (actual path written)
  - `size_bytes`: int (new file size)
  - `split_triggered`: bool (whether file exceeded threshold)
  - `new_files`: List[str] (if split occurred, list of new file paths)

**Behavior:**
1. Read existing file (if it exists)
2. Agent analyzes existing content + new content
3. Agent rewrites file to incorporate new information
4. If file size exceeds 10KB threshold, trigger split operation
5. Return result

**Example:**
```python
# Update root memory
result = write_memory("User prefers Python 3.11+")

# Update specific file
result = write_memory(
    "Silica uses pytest for testing",
    path="projects/silica"
)

# Check if split occurred
if result.split_triggered:
    print(f"Memory split into: {result.new_files}")
```

### search_memory(query: str, max_results: int = 10) -> List[SearchResult]

Agentically search through memory by traversing the graph structure.

**Parameters:**
- `query`: Natural language search query
- `max_results`: Maximum number of results to return

**Returns:**
- List of `SearchResult` objects containing:
  - `path`: str (path to memory file)
  - `excerpt`: str (relevant excerpt from the file)
  - `relevance_score`: float (0-1)
  - `context`: str (brief context about where this fits in memory graph)

**Behavior:**
1. Start at root `memory` file
2. Agent analyzes query against current file content
3. Agent decides whether to:
   - Return excerpts from current file
   - Follow links to child files
   - Both
4. Recursively traverse promising paths
5. Rank and return results

**Example:**
```python
results = search_memory("What Python version does Silica use?")
for result in results:
    print(f"{result.path}: {result.excerpt}")
```

### list_memory_files() -> List[MemoryFileInfo]

List all memory files in the system.

**Returns:**
- List of `MemoryFileInfo` objects containing:
  - `path`: str
  - `size_bytes`: int
  - `last_updated`: datetime
  - `links_to`: List[str] (child file paths)
  - `linked_from`: List[str] (parent file paths)

**Example:**
```python
files = list_memory_files()
for file in files:
    print(f"{file.path} ({file.size_bytes} bytes)")
```

### get_memory_graph() -> Dict

Get the entire memory graph structure for visualization.

**Returns:**
- Dictionary representing the graph:
  ```python
  {
      "nodes": [
          {"id": "memory", "size": 8234, "label": "Root"},
          {"id": "projects/silica", "size": 5432, "label": "Silica Project"}
      ],
      "edges": [
          {"from": "memory", "to": "projects/silica", "label": "Python projects"}
      ]
  }
  ```

## Split Operation

### When to Split

- File size exceeds 10KB (10,240 bytes)
- Triggered automatically after write operations
- Can be manually triggered via `split_memory(path)`

### Split Strategy

Agent analyzes file content and chooses a strategy:

1. **Topic Clustering**: Group by semantic topics
   - Example: Split `memory` into `projects`, `knowledge`, `preferences`

2. **Chronological**: Group by time periods
   - Example: Split logs into `2024-q1`, `2024-q2`, etc.

3. **Entity-based**: Group by entities (people, projects, technologies)
   - Example: Split projects into individual project files

4. **Size-based**: Split large lists or collections
   - Example: Split long lists into numbered chunks

### Split Process

1. Agent reads file content
2. Agent analyzes content structure and semantics
3. Agent proposes split strategy (logged for transparency)
4. Agent creates new files with appropriate content
5. Agent updates original file with:
   - Summary/routing information
   - Links to new files
   - Content that doesn't fit new categories
6. Returns list of new file paths

### Example Split

**Before (memory - 12KB):**
```markdown
# Memory

## Projects
Working on Silica, a Python agent framework...
[3KB of Silica content]

Also working on PersonalWebsite...
[3KB of PersonalWebsite content]

## Knowledge
Python best practices...
[3KB of Python knowledge]

## Preferences
User prefers dark mode...
[2KB of preferences]
```

**After Split:**

**memory (2KB):**
```markdown
# Memory

This is the root of my memory system.

## Projects
I'm working on several software projects. See [[projects]] for details.

## Knowledge
Technical knowledge and learnings. See [[knowledge]] for details.

## Preferences
User prefers dark mode, Python 3.11+, and concise explanations.

## Links
- [[projects]] - Software projects I'm working on
- [[knowledge]] - Technical knowledge and best practices
```

**projects (3KB):**
```markdown
# Projects

## Silica
A Python agent framework for autonomous software development...
[Silica content]

Also see [[projects/silica]] for detailed information.

## PersonalWebsite
[PersonalWebsite content]

## Links
- [[projects/silica]] - Detailed Silica project information
```

**knowledge (3KB):**
```markdown
# Knowledge

## Python
[Python knowledge content]
```

## Storage Backends

### Abstract Interface

```python
class MemoryStorage(ABC):
    @abstractmethod
    def read(self, path: str) -> str:
        """Read memory file content"""
        pass
    
    @abstractmethod
    def write(self, path: str, content: str) -> None:
        """Write memory file content"""
        pass
    
    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if memory file exists"""
        pass
    
    @abstractmethod
    def list_files(self) -> List[str]:
        """List all memory file paths"""
        pass
    
    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete memory file"""
        pass
    
    @abstractmethod
    def get_size(self, path: str) -> int:
        """Get file size in bytes"""
        pass
    
    @abstractmethod
    def get_modified_time(self, path: str) -> datetime:
        """Get last modified timestamp"""
        pass
```

### Local Disk Implementation

**Storage Location:**
- Default: `~/.silica/memory_v2/`
- Configurable via environment variable: `SILICA_MEMORY_PATH`

**File Structure:**
```
~/.silica/memory_v2/
├── memory                    # Root file
├── projects                  # Child file
├── projects/silica          # Nested child
├── knowledge
└── .metadata/               # System metadata
    ├── graph.json           # Cached graph structure
    └── index.json           # Search index (optional)
```

**Implementation Notes:**
- Use pathlib for cross-platform compatibility
- Files are plain text (UTF-8 encoding)
- Atomic writes using temp file + rename
- File locking for concurrent access

### S3 Implementation

**Storage Location:**
- Bucket: Configurable via `SILICA_MEMORY_S3_BUCKET`
- Prefix: Configurable via `SILICA_MEMORY_S3_PREFIX` (default: `memory/`)

**S3 Structure:**
```
s3://my-bucket/memory/
├── memory                    # Root file (object)
├── projects                  # Child file (object)
├── projects/silica          # Nested child (object)
├── knowledge
└── .metadata/
    ├── graph.json
    └── index.json
```

**Implementation Notes:**
- Use boto3 for S3 access
- Content-Type: `text/plain; charset=utf-8`
- Use object metadata for timestamps
- Optional: Use S3 versioning for history
- Caching strategy:
  - Cache frequently accessed files locally
  - TTL-based cache invalidation
  - Use ETag for cache validation

**Configuration:**
```python
# Environment variables
SILICA_MEMORY_BACKEND=s3  # or 'local'
SILICA_MEMORY_S3_BUCKET=my-silica-memory
SILICA_MEMORY_S3_PREFIX=memory/
SILICA_MEMORY_S3_REGION=us-east-1
```

## Migration from V1

### Migration Tool: `migrate_memory_v1_to_v2`

Converts existing hierarchical memory structure to new single-file-based structure.

**Process:**

1. **Scan V1 Structure**: Recursively read all memory files from existing structure
2. **Analyze Content**: Use agent to understand content and relationships
3. **Create Initial Memory File**: Consolidate content into root `memory` file
4. **Organize by Importance**: 
   - Most frequently accessed content stays in root
   - Related content grouped together
   - Low-priority content can be immediately split into child files
5. **Preserve Relationships**: Maintain semantic links between topics
6. **Generate Report**: List what was migrated where

**Command:**
```bash
# Dry run (show what would happen)
silica memory migrate --dry-run

# Perform migration
silica memory migrate

# Specify custom paths
silica memory migrate --from ~/.silica/memory --to ~/.silica/memory_v2
```

**Migration Strategy:**

Option 1: **Flatten and Merge**
- Combine all V1 files into single root file
- Let organic growth re-split as needed
- Simpler, but loses existing organization

Option 2: **Preserve Structure**
- Map V1 hierarchy to V2 files
- Top-level dirs become child files
- Maintain links based on original structure
- More complex, but preserves work

**Recommendation**: Use Option 2 with agent-driven consolidation. Agent reviews the V1 structure and intelligently merges similar content.

### Example Migration

**V1 Structure:**
```
memory/
├── projects/
│   ├── silica/
│   │   ├── architecture
│   │   └── features
│   └── personal_website
├── knowledge/
│   ├── python/
│   │   ├── async
│   │   └── testing
│   └── typescript
└── profile/
    └── preferences
```

**V2 Structure (after migration):**
```
memory                       # Root with overview + routing
projects                     # Consolidated projects
projects/silica             # Detailed Silica info
knowledge                   # Consolidated knowledge
knowledge/python            # Python-specific knowledge
```

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Define storage interface
- [ ] Implement local disk storage
- [ ] Implement basic read/write operations
- [ ] File size monitoring
- [ ] Basic tests

### Phase 2: Agentic Operations
- [ ] Implement write_memory with read-update pattern
- [ ] Implement split detection and triggering
- [ ] Implement split strategy agent
- [ ] Implement search_memory with traversal
- [ ] Advanced tests

### Phase 3: S3 Backend
- [ ] Implement S3 storage backend
- [ ] Caching layer
- [ ] Configuration management
- [ ] S3-specific tests

### Phase 4: Migration
- [ ] Implement V1 scanner
- [ ] Implement migration agent
- [ ] Implement migration CLI
- [ ] Migration tests and validation

### Phase 5: Polish
- [ ] Memory graph visualization
- [ ] Web UI integration
- [ ] Performance optimization
- [ ] Documentation

## Configuration

```python
# config.py or environment variables

MEMORY_V2_BACKEND = "local"  # or "s3"
MEMORY_V2_SIZE_THRESHOLD = 10240  # 10KB in bytes
MEMORY_V2_LOCAL_PATH = "~/.silica/memory_v2"
MEMORY_V2_S3_BUCKET = None
MEMORY_V2_S3_PREFIX = "memory/"
MEMORY_V2_S3_REGION = "us-east-1"
MEMORY_V2_CACHE_ENABLED = True
MEMORY_V2_CACHE_TTL = 300  # 5 minutes
```

## Testing Strategy

### Unit Tests
- Storage backend implementations
- File read/write operations
- Size threshold detection
- Metadata parsing

### Integration Tests
- Write-split-read cycle
- Search across multiple files
- Migration from V1 to V2
- S3 backend with mocked boto3

### Agent Tests
- Split strategy decisions (use frozen LLM responses)
- Search traversal logic
- Write incorporation quality
- Edge cases (empty files, very large files, etc.)

### Performance Tests
- Large memory graphs (100+ files)
- Search performance
- S3 latency with caching
- Concurrent access

## Success Criteria

1. **Simplicity**: New users can understand the system in < 5 minutes
2. **Organic Growth**: Memory structure emerges naturally from usage
3. **Performance**: Search returns results in < 2 seconds for typical usage
4. **Reliability**: No data loss during splits or migrations
5. **Flexibility**: Easy to switch between local and S3 storage
6. **Transparency**: Clear logs of agent decisions during splits

## Open Questions

1. **Circular References**: How to handle if agent creates circular links?
   - Proposed: Track traversal path, prevent revisiting

2. **Merge Operations**: Should we support merging files back together?
   - Proposed: Phase 6 feature, triggered when multiple files stay small

3. **Concurrent Writes**: How to handle race conditions?
   - Local: File locking
   - S3: Optimistic concurrency with ETags

4. **Search Index**: Should we maintain a separate search index?
   - Proposed: Optional optimization, not required for MVP

5. **History/Versioning**: Should we track content history?
   - Local: Could use git
   - S3: Use S3 versioning
   - Proposed: Phase 6 feature

## Comparison with V1

| Aspect | V1 (Current) | V2 (Proposed) |
|--------|--------------|---------------|
| Initial structure | Predetermined hierarchy | Single file |
| Growth | Manual path specification | Automatic splitting |
| Organization | User/system defined | Agent defined |
| Complexity | High (tree + critique) | Low (files + links) |
| Learning curve | Steep | Gentle |
| Storage | Local files | Local or S3 |
| Search | Ripgrep | Agentic traversal |
| Write | Targeted updates | Read-update pattern |

## Example Usage Scenarios

### Scenario 1: New User

```python
# First memory
write_memory("I'm working on a Python project called Silica")
# Creates: memory (145 bytes)

# Add more information
write_memory("Silica uses pytest for testing and ruff for linting")
# Updates: memory (289 bytes)

# Keep adding...
# ... eventually ...

# Triggers split at 10KB
write_memory("Added new feature for GitHub integration")
# Creates: projects, knowledge
# Updates: memory with routing information
```

### Scenario 2: Searching

```python
# Search for information
results = search_memory("How does Silica handle testing?")

# Agent process:
# 1. Read memory (root)
# 2. See link to "projects"
# 3. Follow link, read projects
# 4. See link to "projects/silica"
# 5. Follow link, read projects/silica
# 6. Find relevant content about pytest
# 7. Return result

print(results[0].excerpt)
# "Silica uses pytest for testing..."
```

### Scenario 3: Complex Organization

After months of use:

```
memory (root)
├── projects
│   ├── projects/silica
│   │   ├── projects/silica/architecture
│   │   └── projects/silica/features
│   └── projects/personal_website
├── knowledge
│   ├── knowledge/python
│   └── knowledge/devops
└── work
    └── work/meetings
```

All emerged organically from actual usage patterns!

## References

- Original memory system: `silica/developer/tools/memory.py`
- Memory web app: `docs/developer/memory_webapp.md`
- Agentic memory placement: `docs/developer/agentic_memory_placement.md`
