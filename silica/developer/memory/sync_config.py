"""Configuration for memory sync engines.

This module provides the SyncConfig dataclass that encapsulates all configuration
needed for a sync engine instance, enabling multiple independent sync namespaces.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SyncConfig:
    """Configuration for a sync engine instance.

    This dataclass encapsulates all the configuration needed to create a sync engine:
    - Remote namespace (where files are stored remotely)
    - Local scan paths (which files/directories to sync)
    - Index file location (where to track sync state)

    By using separate configs, multiple sync engines can operate independently.
    """

    namespace: str  # Remote namespace (e.g., "personas/default/memory")
    scan_paths: list[Path]  # Local directories/files to scan
    index_file: Path  # Local index file path

    @classmethod
    def for_memory(cls, persona_name: str, persona_dir: Path) -> "SyncConfig":
        """Create configuration for memory sync.

        Memory sync includes:
        - The persona's memory directory
        - The persona.md file (persona definition)

        Args:
            persona_name: Name of the persona (e.g., "default")
            persona_dir: Base directory for the persona

        Returns:
            SyncConfig configured for memory sync

        Example:
            >>> config = SyncConfig.for_memory("default", Path("~/.silica/personas/default"))
            >>> config.namespace
            'personas/default/memory'
        """
        persona_dir = Path(persona_dir)

        return cls(
            namespace=f"personas/{persona_name}/memory",
            scan_paths=[
                persona_dir / "memory",
                persona_dir / "persona.md",  # Special: persona definition
            ],
            index_file=persona_dir / ".sync-index-memory.json",
        )

    @classmethod
    def for_history(
        cls, persona_name: str, persona_dir: Path, session_id: str
    ) -> "SyncConfig":
        """Create configuration for session history sync.

        History sync is per-session:
        - Only syncs files for the specified session
        - Index and log are stored in the session directory

        Args:
            persona_name: Name of the persona (e.g., "default")
            persona_dir: Base directory for the persona
            session_id: Session identifier (e.g., "session-123")

        Returns:
            SyncConfig configured for history sync

        Example:
            >>> config = SyncConfig.for_history("default",
            ...                                  Path("~/.silica/personas/default"),
            ...                                  "session-123")
            >>> config.namespace
            'personas/default/history/session-123'
        """
        persona_dir = Path(persona_dir)
        session_dir = persona_dir / "history" / session_id

        return cls(
            namespace=f"personas/{persona_name}/history/{session_id}",
            scan_paths=[session_dir],
            index_file=session_dir / ".sync-index.json",
        )
