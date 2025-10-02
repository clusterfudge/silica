"""
Exceptions for Memory V2 system.
"""


class MemoryError(Exception):
    """Base exception for memory operations."""


class MemoryNotFoundError(MemoryError):
    """Raised when a memory file is not found."""


class MemoryStorageError(MemoryError):
    """Raised when a storage operation fails."""


class MemoryInvalidPathError(MemoryError):
    """Raised when a memory path is invalid."""
