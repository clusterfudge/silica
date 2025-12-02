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
    - Base directory (where files are read from / written to)

    By using separate configs, multiple sync engines can operate independently.
    """

    namespace: str  # Remote namespace (e.g., "personas/default/memory")
    scan_paths: list[Path]  # Local directories/files to scan
    index_file: Path  # Local index file path
    base_dir: Path  # Base directory for file operations

    @classmethod
    def for_memory(cls, persona_name: str) -> "SyncConfig":
        """Create configuration for memory sync.

        Memory sync includes:
        - The persona's memory directory
        - The persona.md file (persona definition)

        Args:
            persona_name: Name of the persona (e.g., "default")

        Returns:
            SyncConfig configured for memory sync

        Example:
            >>> config = SyncConfig.for_memory("default")
            >>> config.namespace
            'personas/default/memory'
        """
        from silica.developer import personas

        persona = personas.get_or_create(persona_name, interactive=False)
        persona_dir = persona.base_directory

        return cls(
            namespace=f"personas/{persona_name}/memory",
            scan_paths=[
                persona_dir / "memory",
                persona_dir / "persona.md",  # Special: persona definition
            ],
            index_file=persona_dir / ".sync-index-memory.json",
            base_dir=persona_dir,  # Files are read/written from persona directory
        )

    @classmethod
    def for_history(cls, persona_name: str, session_id: str) -> "SyncConfig":
        """Create configuration for session history sync.

        History sync is per-session:
        - Only syncs files for the specified session
        - Index and log are stored in the session directory

        Args:
            persona_name: Name of the persona (e.g., "default")
            session_id: Session identifier (e.g., "session-123")

        Returns:
            SyncConfig configured for history sync

        Example:
            >>> config = SyncConfig.for_history("default", "session-123")
            >>> config.namespace
            'personas/default/history/session-123'
        """
        from silica.developer import personas

        persona = personas.get_or_create(persona_name, interactive=False)
        persona_dir = persona.base_directory
        session_dir = persona_dir / "history" / session_id

        return cls(
            namespace=f"personas/{persona_name}/history/{session_id}",
            scan_paths=[session_dir],
            index_file=session_dir / ".sync-index-history.json",
            base_dir=persona_dir,  # Files are read/written from persona directory
        )
