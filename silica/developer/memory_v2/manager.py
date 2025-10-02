"""
Memory Manager for Memory V2 system.

The MemoryManager is responsible for tracking the root directory of storage
and providing a clean interface to the storage backend. Each persona gets
its own isolated memory space.
"""

import os
from pathlib import Path
from typing import Optional

from .storage import LocalDiskStorage, MemoryStorage


class MemoryManager:
    """
    Manager for Memory V2 system.

    Handles persona-specific memory isolation and provides a clean interface
    to the underlying storage backend.

    Each persona gets its own memory directory:
    - ~/.silica/memory_v2/coding_agent/
    - ~/.silica/memory_v2/deep_research_agent/
    - ~/.silica/memory_v2/default/
    """

    def __init__(
        self,
        persona_name: Optional[str] = None,
        base_path: Optional[str] = None,
        storage_backend: Optional[MemoryStorage] = None,
    ):
        """
        Initialize the memory manager.

        Args:
            persona_name: Name of the persona. If None or unknown, uses "default".
                         This becomes part of the storage path for isolation.
            base_path: Base directory for all memory storage.
                      Defaults to ~/.silica/memory_v2/
            storage_backend: Optional custom storage backend. If None, uses
                           LocalDiskStorage with persona-specific path.
        """
        # Determine the persona name
        self.persona_name = self._resolve_persona_name(persona_name)

        # Determine base path
        if base_path is None:
            base_path = os.environ.get(
                "MEMORY_V2_PATH", str(Path.home() / ".silica" / "memory_v2")
            )

        # Create persona-specific path
        self.persona_path = Path(base_path) / self.persona_name

        # Initialize storage backend
        if storage_backend is None:
            self.storage = LocalDiskStorage(self.persona_path)
        else:
            self.storage = storage_backend

    def _resolve_persona_name(self, persona_name: Optional[str]) -> str:
        """
        Resolve the persona name, using default if none provided.

        The memory system simply accepts any persona name as a string
        and uses it for directory isolation. Persona validation happens
        elsewhere (in hdev.py where actual persona prompts are used).

        Args:
            persona_name: Requested persona name

        Returns:
            The persona name or "default" if none provided
        """
        return persona_name if persona_name else "default"

    @property
    def root_path(self) -> Path:
        """Get the root path for this persona's memory storage."""
        return self.persona_path

    def __repr__(self) -> str:
        """String representation of the manager."""
        return (
            f"MemoryManager(persona='{self.persona_name}', path='{self.persona_path}')"
        )
