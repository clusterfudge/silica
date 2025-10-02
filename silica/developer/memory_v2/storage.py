"""
Storage backends for Memory V2 system.

This module provides an abstract storage interface and implementations
for different storage backends (local disk, S3, etc.).
"""

import os
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List
import fcntl

from .exceptions import (
    MemoryNotFoundError,
    MemoryStorageError,
    MemoryInvalidPathError,
)


class MemoryStorage(ABC):
    """
    Abstract base class for memory storage backends.

    This interface defines the contract that all storage implementations
    must follow, allowing easy swapping between local disk, S3, or other
    storage mechanisms.
    """

    @abstractmethod
    def read(self, path: str) -> str:
        """
        Read memory file content.

        Args:
            path: Path to the memory file (relative to storage root)

        Returns:
            String content of the file

        Raises:
            MemoryNotFoundError: If the file doesn't exist
            MemoryStorageError: If reading fails
        """

    @abstractmethod
    def write(self, path: str, content: str) -> None:
        """
        Write memory file content.

        Args:
            path: Path to the memory file (relative to storage root)
            content: Content to write

        Raises:
            MemoryStorageError: If writing fails
        """

    @abstractmethod
    def exists(self, path: str) -> bool:
        """
        Check if memory file exists.

        Args:
            path: Path to the memory file

        Returns:
            True if file exists, False otherwise
        """

    @abstractmethod
    def list_files(self) -> List[str]:
        """
        List all memory file paths.

        Returns:
            List of relative paths to all memory files
        """

    @abstractmethod
    def delete(self, path: str) -> None:
        """
        Delete memory file.

        Args:
            path: Path to the memory file

        Raises:
            MemoryNotFoundError: If the file doesn't exist
            MemoryStorageError: If deletion fails
        """

    @abstractmethod
    def get_size(self, path: str) -> int:
        """
        Get file size in bytes.

        Args:
            path: Path to the memory file

        Returns:
            File size in bytes

        Raises:
            MemoryNotFoundError: If the file doesn't exist
        """

    @abstractmethod
    def get_modified_time(self, path: str) -> datetime:
        """
        Get last modified timestamp.

        Args:
            path: Path to the memory file

        Returns:
            Last modified datetime

        Raises:
            MemoryNotFoundError: If the file doesn't exist
        """


class LocalDiskStorage(MemoryStorage):
    """
    Local file system storage implementation.

    Stores memory files in a local directory with atomic writes
    and file locking for concurrent access safety.
    """

    def __init__(self, base_path: str | Path | None = None):
        """
        Initialize local disk storage.

        Args:
            base_path: Base directory for memory storage.
                      Defaults to ~/.silica/memory_v2/
        """
        if base_path is None:
            base_path = Path.home() / ".silica" / "memory_v2"

        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

        # Create metadata directory
        self.metadata_path = self.base_path / ".metadata"
        self.metadata_path.mkdir(exist_ok=True)

    def _validate_path(self, path: str) -> Path:
        """
        Validate and normalize a memory file path.

        Args:
            path: Relative path to validate

        Returns:
            Resolved absolute path

        Raises:
            MemoryInvalidPathError: If path is invalid or escapes base directory
        """
        if not path:
            raise MemoryInvalidPathError("Path cannot be empty")

        # Normalize path separators
        path = path.replace("\\", "/")

        # Check for dangerous path components
        if ".." in path.split("/"):
            raise MemoryInvalidPathError(f"Path cannot contain '..': {path}")

        if path.startswith("/"):
            raise MemoryInvalidPathError(f"Path must be relative: {path}")

        # Resolve full path
        full_path = (self.base_path / path).resolve()

        # Ensure it's within base_path
        try:
            full_path.relative_to(self.base_path)
        except ValueError:
            raise MemoryInvalidPathError(f"Path escapes base directory: {path}")

        return full_path

    def read(self, path: str) -> str:
        """Read memory file content with file locking."""
        full_path = self._validate_path(path)

        if not full_path.exists():
            raise MemoryNotFoundError(f"Memory file not found: {path}")

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                # Acquire shared lock for reading
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    content = f.read()
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            return content
        except Exception as e:
            raise MemoryStorageError(f"Failed to read {path}: {e}")

    def write(self, path: str, content: str) -> None:
        """
        Write memory file content atomically.

        Uses atomic write (temp file + rename) to ensure consistency
        and exclusive locking to prevent concurrent write conflicts.
        """
        full_path = self._validate_path(path)

        # Ensure parent directory exists and is a directory
        if full_path.parent != self.base_path:
            # Check if parent path conflicts with existing file
            if full_path.parent.exists() and not full_path.parent.is_dir():
                raise MemoryStorageError(
                    f"Cannot create directory {full_path.parent.relative_to(self.base_path)}: "
                    f"a file with that name already exists"
                )
            full_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Write to temporary file first
            fd, temp_path = tempfile.mkstemp(
                dir=full_path.parent,
                prefix=f".{full_path.name}.",
                suffix=".tmp",
                text=True,
            )

            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    # Acquire exclusive lock
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

                # Atomic rename
                os.replace(temp_path, full_path)
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                raise

        except Exception as e:
            raise MemoryStorageError(f"Failed to write {path}: {e}")

    def exists(self, path: str) -> bool:
        """Check if memory file exists."""
        try:
            full_path = self._validate_path(path)
            return full_path.exists() and full_path.is_file()
        except MemoryInvalidPathError:
            return False

    def list_files(self) -> List[str]:
        """
        List all memory file paths recursively.

        Returns relative paths, excluding metadata directory.
        """
        files = []

        for full_path in self.base_path.rglob("*"):
            # Skip directories
            if not full_path.is_file():
                continue

            # Skip metadata directory
            try:
                full_path.relative_to(self.metadata_path)
                continue  # This is in metadata dir, skip it
            except ValueError:
                pass  # Not in metadata dir, keep it

            # Get relative path
            rel_path = full_path.relative_to(self.base_path)
            files.append(str(rel_path).replace("\\", "/"))

        return sorted(files)

    def delete(self, path: str) -> None:
        """Delete memory file."""
        full_path = self._validate_path(path)

        if not full_path.exists():
            raise MemoryNotFoundError(f"Memory file not found: {path}")

        try:
            full_path.unlink()
        except Exception as e:
            raise MemoryStorageError(f"Failed to delete {path}: {e}")

    def get_size(self, path: str) -> int:
        """Get file size in bytes."""
        full_path = self._validate_path(path)

        if not full_path.exists():
            raise MemoryNotFoundError(f"Memory file not found: {path}")

        try:
            return full_path.stat().st_size
        except Exception as e:
            raise MemoryStorageError(f"Failed to get size of {path}: {e}")

    def get_modified_time(self, path: str) -> datetime:
        """Get last modified timestamp."""
        full_path = self._validate_path(path)

        if not full_path.exists():
            raise MemoryNotFoundError(f"Memory file not found: {path}")

        try:
            timestamp = full_path.stat().st_mtime
            return datetime.fromtimestamp(timestamp)
        except Exception as e:
            raise MemoryStorageError(f"Failed to get modified time of {path}: {e}")
