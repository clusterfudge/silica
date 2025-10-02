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


@dataclass
class MigrationState:
    """Tracks migration progress for resumability."""

    started_at: str
    last_updated: str
    processed_files: List[Dict[str, Any]]
    total_files: int
    completed: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MigrationState":
        """Create from dictionary."""
        return cls(**data)


def get_v1_memory_path() -> Path:
    """Get the path to V1 memory system."""
    # Default V1 location
    v1_path = Path.home() / ".silica" / "memory"
    return v1_path


def scan_v1_memory(v1_path: Optional[Path] = None) -> List[V1MemoryFile]:
    """
    Scan V1 memory directory and return all files sorted by modification time.

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
    for file_path in v1_path.rglob("*"):
        # Skip directories and hidden files
        if file_path.is_dir():
            continue
        if file_path.name.startswith("."):
            continue

        # Get relative path from V1 memory root
        rel_path = file_path.relative_to(v1_path)

        # Get file stats
        stat = file_path.stat()

        files.append(
            V1MemoryFile(
                path=str(rel_path),
                full_path=file_path,
                size_bytes=stat.st_size,
                last_modified=datetime.fromtimestamp(stat.st_mtime),
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


async def extract_information_from_file(
    v1_file: V1MemoryFile, context: AgentContext
) -> str:
    """
    Use an AI agent to extract salient information from a V1 memory file.

    The agent reads the file and extracts:
    - Key facts and concepts
    - Important relationships
    - Actionable information
    - Context and metadata

    Args:
        v1_file: V1 memory file to process
        context: Agent context for sub-agent execution

    Returns:
        Extracted information as formatted text
    """
    from silica.developer.tools.subagent import run_agent

    # Load file content if not already loaded
    if v1_file.content is None:
        try:
            with open(v1_file.full_path, "r", encoding="utf-8") as f:
                v1_file.content = f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    # Create extraction prompt
    extraction_prompt = f"""You are migrating information from an old memory system to a new one.

**File**: {v1_file.path}
**Last Modified**: {v1_file.last_modified.strftime("%Y-%m-%d %H:%M:%S")}
**Size**: {v1_file.size_bytes} bytes

**Content**:
```
{v1_file.content}
```

**Your task**: Extract and summarize the salient information from this file.

Focus on:
1. **Key Facts**: Important information, data, or knowledge
2. **Concepts**: Ideas, principles, or understanding
3. **Relationships**: Connections between entities, projects, or topics
4. **Context**: When, why, or how this information matters
5. **Actionable Items**: Things to remember or act on

**Guidelines**:
- Be concise but preserve important details
- Maintain context and relationships
- Identify the type of information (project, knowledge, note, etc.)
- Note any temporal context (if this is time-sensitive)
- Skip redundant or trivial information
- Use clear, structured format

**Output format**:
```
Type: [project/knowledge/note/reference/etc]
Topic: [main subject]

Summary:
[Concise summary of the content]

Key Information:
- [Important fact 1]
- [Important fact 2]
- [etc]

Context: [When/why this matters]
Related: [Links to other topics/concepts]
```

Extract the information now. Be thorough but concise.
"""

    # Run extraction agent with no tools (just analysis)
    try:
        extracted = await run_agent(
            context=context,
            prompt=extraction_prompt,
            tool_names=[],  # No tools needed - pure analysis
            system=None,
            model="smart",  # Use smart model for analysis
        )
        return extracted
    except Exception as e:
        return f"Error extracting information: {e}"


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

    # Import tools for storage
    from silica.developer.memory_v2.operations import agentic_write

    # Process files with progress tracking
    success_count = 0
    error_count = 0
    errors = []

    for i, v1_file in enumerate(files_to_process):
        try:
            # Extract information using AI
            extracted_info = await extract_information_from_file(v1_file, context)

            # Store extracted information using agentic write to root
            # Let the AI decide how to incorporate this information
            result = await agentic_write(
                storage=storage,
                path="",  # Store at root, let organic growth handle organization
                new_content=f"# Migrated from V1: {v1_file.path}\n\n{extracted_info}",
                context=context,
                instruction=f"This is information migrated from the old memory system (file: {v1_file.path}). "
                f"Incorporate this information appropriately, organizing by topic or theme. "
                f"Avoid duplication with existing content.",
            )

            if result.success:
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
                errors.append(f"{v1_file.path}: Write failed")

        except Exception as e:
            error_count += 1
            errors.append(f"{v1_file.path}: {str(e)}")

            # Still record in state as attempted
            state.processed_files.append(
                {
                    "path": v1_file.path,
                    "processed_at": datetime.now().isoformat(),
                    "success": False,
                    "error": str(e),
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
