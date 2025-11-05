"""Conflict resolution for memory sync.

This module provides an abstract interface for resolving sync conflicts,
with implementations for LLM-based merging and mock resolvers for testing.
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
            local_content: Current local file content (written first)
            remote_content: Current remote file content (incoming update)

        Returns:
            Merged content as bytes

        Raises:
            ConflictResolutionError: If merge fails
        """


class MockConflictResolver(ConflictResolver):
    """Mock resolver for testing.

    Can be configured to pick local, remote, or raise errors.
    """

    def __init__(self, strategy: str = "local"):
        """Initialize mock resolver.

        Args:
            strategy: One of "local", "remote", or "error"
        """
        if strategy not in ("local", "remote", "error"):
            raise ValueError(f"Invalid strategy: {strategy}")
        self.strategy = strategy

    def resolve_conflict(
        self,
        path: str,
        local_content: bytes,
        remote_content: bytes,
    ) -> bytes:
        """Resolve conflict according to configured strategy."""
        if self.strategy == "error":
            raise ConflictResolutionError("Mock resolver configured to fail")
        elif self.strategy == "local":
            return local_content
        else:  # remote
            return remote_content
