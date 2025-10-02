"""
Migration tools for Memory V1 to V2.

This module provides intelligent migration from the hierarchical V1 memory system
to the simpler, organic V2 system with AI-powered content extraction.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from silica.developer.context import AgentContext
from silica.developer.memory_v2.storage import MemoryStorage


@dataclass
class V1MemoryFile:
    """Represents a file in the V1 memory system."""

    path: str  # Relative path from V1 memory root
    full_path: Path  # Absolute path
    size_bytes: int
    last_modified: datetime
    content: Optional[str] = None  # Loaded on demand
    metadata: Optional[Dict[str, Any]] = None  # Metadata from .metadata.json


@dataclass
class MigrationState:
    """Tracks migration progress for resumability."""

    started_at: str
    last_updated: str
    processed_files: List[Dict[str, Any]]
    total_files: int
    completed: bool = False
    # Cost tracking
    total_cost: float = 0.0
    total_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MigrationState":
        """Create from dictionary."""
        # Handle old state files without cost tracking
        if "total_cost" not in data:
            data["total_cost"] = 0.0
        if "total_tokens" not in data:
            data["total_tokens"] = 0
        if "total_prompt_tokens" not in data:
            data["total_prompt_tokens"] = 0
        if "total_completion_tokens" not in data:
            data["total_completion_tokens"] = 0
        return cls(**data)


def get_v1_memory_path() -> Path:
    """Get the path to V1 memory system."""
    # Default V1 location
    v1_path = Path.home() / ".silica" / "memory"
    return v1_path


def load_v1_metadata(md_file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Load metadata from a .metadata.json file corresponding to a .md file.

    Args:
        md_file_path: Path to the .md file

    Returns:
        Dictionary with metadata, or None if metadata file doesn't exist
    """
    # Check for corresponding .metadata.json file
    metadata_path = md_file_path.parent / f"{md_file_path.name}.metadata.json"

    if not metadata_path.exists():
        return None

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def scan_v1_memory(v1_path: Optional[Path] = None) -> List[V1MemoryFile]:
    """
    Scan V1 memory directory and return all markdown files sorted by modification time.

    Only processes .md files, ignoring .json files. Loads metadata from corresponding
    .metadata.json files if they exist.

    Args:
        v1_path: Path to V1 memory directory (defaults to ~/.silica/memory)

    Returns:
        List of V1MemoryFile objects sorted chronologically (oldest first)
    """
    if v1_path is None:
        v1_path = get_v1_memory_path()

    if not v1_path.exists():
        return []

    files = []

    # Walk the V1 memory directory
    for file_path in v1_path.rglob("*.md"):
        # Skip directories and hidden files
        if file_path.is_dir():
            continue
        if file_path.name.startswith("."):
            continue

        # Get relative path from V1 memory root
        rel_path = file_path.relative_to(v1_path)

        # Get file stats
        stat = file_path.stat()

        # Load metadata if available
        metadata = load_v1_metadata(file_path)

        files.append(
            V1MemoryFile(
                path=str(rel_path),
                full_path=file_path,
                size_bytes=stat.st_size,
                last_modified=datetime.fromtimestamp(stat.st_mtime),
                metadata=metadata,
            )
        )

    # Sort by modification time (oldest first)
    files.sort(key=lambda f: f.last_modified)

    return files


def load_migration_state(storage: MemoryStorage) -> Optional[MigrationState]:
    """
    Load migration state from storage.

    Args:
        storage: V2 storage backend

    Returns:
        MigrationState if exists, None otherwise
    """
    try:
        # Migration state stored in metadata
        pass

        if hasattr(storage, "metadata_path"):
            state_file = storage.metadata_path / "migration_state.json"
            if state_file.exists():
                with open(state_file, "r") as f:
                    data = json.load(f)
                return MigrationState.from_dict(data)
    except Exception:
        pass

    return None


def save_migration_state(storage: MemoryStorage, state: MigrationState) -> None:
    """
    Save migration state to storage.

    Args:
        storage: V2 storage backend
        state: Migration state to save
    """
    try:
        if hasattr(storage, "metadata_path"):
            state_file = storage.metadata_path / "migration_state.json"
            state.last_updated = datetime.now().isoformat()

            with open(state_file, "w") as f:
                json.dump(state.to_dict(), f, indent=2)
    except Exception:
        pass


async def extract_and_store_v1_file(
    v1_file: V1MemoryFile, storage: MemoryStorage, context: AgentContext
) -> tuple[bool, str]:
    """
    Extract salient information from a V1 file and intelligently store it in V2.

    This is the core migration function that:
    1. Reads the V1 file content
    2. Uses AI to extract key facts, concepts, and relationships (not dump entire file)
    3. Uses AI to determine the best location in V2 memory hierarchy
    4. Stores the extracted information using agentic write

    The goal is NOT to preserve the entire V1 file structure or content verbatim.
    Instead, we extract and distill:
    - Important facts about individuals, projects, technologies
    - Current project states and decisions
    - Best practices and learnings
    - Actionable information
    - Relevant context

    Trivial, redundant, or outdated information is intentionally discarded.

    Args:
        v1_file: V1 memory file to process
        storage: V2 storage backend
        context: Agent context for AI operations

    Returns:
        Tuple of (success, message)
    """
    from silica.developer.tools.subagent import run_agent

    # Load file content if not already loaded
    if v1_file.content is None:
        try:
            with open(v1_file.full_path, "r", encoding="utf-8") as f:
                v1_file.content = f.read()
        except Exception as e:
            return False, f"Error reading file: {e}"

    # Format metadata if available
    metadata_section = ""
    if v1_file.metadata:
        metadata_section = "\n**Metadata**:\n"

        # Format timestamps
        if "created" in v1_file.metadata:
            try:
                created = datetime.fromtimestamp(float(v1_file.metadata["created"]))
                metadata_section += (
                    f"- Created: {created.strftime('%Y-%m-%d %H:%M:%S')}\n"
                )
            except (ValueError, TypeError):
                pass

        if "updated" in v1_file.metadata:
            try:
                updated = datetime.fromtimestamp(float(v1_file.metadata["updated"]))
                metadata_section += (
                    f"- Updated: {updated.strftime('%Y-%m-%d %H:%M:%S')}\n"
                )
            except (ValueError, TypeError):
                pass

        # Include summary if present
        if "summary" in v1_file.metadata:
            metadata_section += f"- Summary: {v1_file.metadata['summary']}\n"

        # Include version if present
        if "version" in v1_file.metadata:
            metadata_section += f"- Version: {v1_file.metadata['version']}\n"

    # Get current V2 structure to help agent make placement decisions
    try:
        existing_files = storage.list_files()
        root_content = storage.read("") if storage.exists("") else "(empty)"
    except Exception:
        existing_files = []
        root_content = "(empty)"

    # Create comprehensive migration prompt for extraction AND placement
    migration_prompt = f"""You are migrating information from an old memory system (V1) to a new organic memory system (V2).

**Source File**: {v1_file.path}
**Last Modified**: {v1_file.last_modified.strftime("%Y-%m-%d %H:%M:%S")}
**Size**: {v1_file.size_bytes} bytes
{metadata_section}

**V1 File Content**:
```
{v1_file.content}
```

**Current V2 Memory Structure**:
- Existing paths: {', '.join(existing_files) if existing_files else '(none - starting fresh)'}

**Current V2 Root Content**:
```
{root_content[:500]}{'...' if len(root_content) > 500 else ''}
```

**YOUR TASK - Complete BOTH steps:**

**STEP 1: Extract Salient Information**

Your goal is NOT to preserve the entire file. Instead, extract and distill:

✅ **DO Extract:**
- Key facts about individuals, projects, companies, technologies
- Current project states, statuses, and recent decisions
- Best practices, learnings, and insights
- Technical details that are reference-worthy (APIs, configs, architectures)
- Important relationships and connections
- Actionable information and context

❌ **DON'T Extract:**
- Redundant information already in V2
- Trivial details (meeting schedules, old status updates)
- Outdated information superseded by newer facts
- Verbose logs or repetitive content
- Information that provides no future value

**Format your extraction concisely**:
```
Type: [project/knowledge/person/company/reference/best-practice/etc]
Topic: [clear, specific topic]

Summary: [1-3 sentences capturing the essence]

Key Facts:
- [Specific, valuable fact #1]
- [Specific, valuable fact #2]
- [etc - only important facts]

Context: [Why this matters, when it's relevant]
Related: [Connections to other topics/concepts if any]
```

**STEP 2: Store in the Right Place**

Now determine WHERE this information belongs in V2 memory:

1. **Use write_memory_agentic** to store the extracted content
2. Choose the appropriate path:
   - `""` (root) - For high-level, cross-cutting information or if unsure
   - `"projects"` - For project-specific information
   - `"knowledge"` - For technical knowledge and best practices
   - `"people"` - For information about individuals
   - `"companies"` or other semantic paths as appropriate
   - Or create new semantic paths if the content warrants it

3. Let the agentic write handle merging with existing content

**GUIDELINES:**
- **Summarize, don't dump** - Extract essence, not entire content
- **Be selective** - Quality over quantity
- **Choose semantic paths** - Organize by meaning, not by V1 structure
- **Avoid duplication** - The agentic write will handle merging
- **One write operation** - Store all extracted content in one appropriate location
- **Provide context in instruction** - Tell write_memory_agentic how to integrate this

**EXAMPLE:**

If you extract information about the "Silica project architecture":
```
write_memory_agentic(
    content='''Type: project/technical-reference
Topic: Silica Memory V2 Architecture

Summary: V2 uses organic growth pattern with single root file that splits at 10KB threshold.

Key Facts:
- Starts with single 'memory' file, grows through AI-driven splitting
- Storage abstraction supports local disk and S3 backends
- Agentic operations for write (merge), search (traverse), and split
- Each node can have both content and children

Context: Core architecture for memory system redesign completed Jan 2025''',
    
    path="projects",
    
    instruction="This is extracted information about Silica project architecture from V1 migration. If there's existing Silica content, merge with it. If not, create new organized section."
)
```

**Now execute the migration for this file. Extract the salient information and store it appropriately.**
"""

    # Run migration agent with write_memory_agentic tool
    try:
        await run_agent(
            context=context,
            prompt=migration_prompt,
            tool_names=["write_memory_agentic", "read_memory", "list_memory_files"],
            system=None,
            model="smart",  # Use smart model for analysis and placement
        )
        return True, "Successfully extracted and stored information"
    except Exception as e:
        return False, f"Error during migration: {e}"


async def migrate_v1_to_v2(
    storage: MemoryStorage,
    context: AgentContext,
    v1_path: Optional[Path] = None,
    resume: bool = True,
    max_files: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Migrate V1 memory to V2 using AI extraction.

    This is the main migration function that:
    1. Scans V1 memory files chronologically
    2. Uses AI to extract information from each file
    3. Stores extracted information in V2
    4. Tracks progress and allows resumption

    Args:
        storage: V2 storage backend
        context: Agent context for sub-agent execution
        v1_path: Path to V1 memory (defaults to ~/.silica/memory)
        resume: Whether to resume from last checkpoint
        max_files: Maximum files to process (None = all)

    Returns:
        Dictionary with migration statistics
    """
    # Load or create migration state
    state = None
    if resume:
        state = load_migration_state(storage)

    # Scan V1 memory
    v1_files = scan_v1_memory(v1_path)

    if not v1_files:
        return {
            "success": False,
            "message": "No V1 memory files found",
            "files_processed": 0,
        }

    # Initialize state if needed
    if state is None:
        state = MigrationState(
            started_at=datetime.now().isoformat(),
            last_updated=datetime.now().isoformat(),
            processed_files=[],
            total_files=len(v1_files),
        )

    # Build set of already processed paths
    processed_paths = {pf["path"] for pf in state.processed_files}

    # Filter to unprocessed files
    files_to_process = [f for f in v1_files if f.path not in processed_paths]

    # Apply max_files limit
    if max_files is not None:
        files_to_process = files_to_process[:max_files]

    if not files_to_process:
        state.completed = True
        save_migration_state(storage, state)
        return {
            "success": True,
            "message": "Migration already complete",
            "files_processed": len(state.processed_files),
            "total_files": state.total_files,
        }

    # Process files with progress tracking
    success_count = 0
    error_count = 0
    errors = []

    for i, v1_file in enumerate(files_to_process):
        try:
            # Extract and store using AI - agent decides where to place content
            success, message = await extract_and_store_v1_file(
                v1_file, storage, context
            )

            if success:
                success_count += 1

                # Record in state
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
                errors.append(f"{v1_file.path}: {message}")

                # Record in state as attempted
                state.processed_files.append(
                    {
                        "path": v1_file.path,
                        "processed_at": datetime.now().isoformat(),
                        "success": False,
                        "error": message,
                    }
                )

        except Exception as e:
            error_count += 1
            error_msg = str(e)
            errors.append(f"{v1_file.path}: {error_msg}")

            # Still record in state as attempted
            state.processed_files.append(
                {
                    "path": v1_file.path,
                    "processed_at": datetime.now().isoformat(),
                    "success": False,
                    "error": error_msg,
                }
            )

        # Save state after each file (for resumability)
        save_migration_state(storage, state)

    # Check if migration is complete
    if len(state.processed_files) >= state.total_files:
        state.completed = True
        save_migration_state(storage, state)

    return {
        "success": error_count == 0,
        "files_processed": success_count,
        "errors": error_count,
        "error_details": errors if errors else None,
        "total_files": state.total_files,
        "remaining": state.total_files - len(state.processed_files),
        "completed": state.completed,
    }
