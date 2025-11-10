"""Conflict resolution for memory sync.

This module provides an abstract interface for resolving sync conflicts.
"""

from abc import ABC, abstractmethod


class ConflictResolutionError(Exception):
    """Raised when conflict resolution fails."""


class ConflictResolver(ABC):
    """Abstract interface for resolving sync conflicts."""

    @abstractmethod
    def resolve_conflict(
        self,
        path: str,
        local_content: bytes,
        remote_content: bytes,
    ) -> bytes:
        """Resolve conflict by merging local and remote content.

        Args:
            path: File path (for context about file type/purpose)
            local_content: Current local file content
            remote_content: Current remote file content

        Returns:
            Merged content as bytes

        Raises:
            ConflictResolutionError: If merge fails
        """
