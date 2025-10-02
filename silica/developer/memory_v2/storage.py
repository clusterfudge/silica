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

    Storage Structure:
    Each memory node is represented as a directory containing a .content file.
    This allows any node to seamlessly transition from leaf to parent:

    memory/
        .content          # The actual content of "memory"
    memory/projects/
        .content          # The actual content of "memory/projects"
    memory/projects/silica/
        .content          # The actual content of "memory/projects/silica"
    """

    CONTENT_FILENAME = ".content"

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
            path: Relative path to validate (e.g., "memory", "projects/silica")

        Returns:
            Resolved absolute path to the node directory

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

        # Resolve full path to the node directory
        full_path = (self.base_path / path).resolve()

        # Ensure it's within base_path
        try:
            full_path.relative_to(self.base_path)
        except ValueError:
            raise MemoryInvalidPathError(f"Path escapes base directory: {path}")

        return full_path

    def _get_content_file_path(self, node_path: Path) -> Path:
        """
        Get the path to the .content file for a node.

        Args:
            node_path: Path to the node directory

        Returns:
            Path to the .content file
        """
        return node_path / self.CONTENT_FILENAME

    def read(self, path: str) -> str:
        """Read memory file content with file locking."""
        node_path = self._validate_path(path)
        content_file = self._get_content_file_path(node_path)

        if not content_file.exists():
            raise MemoryNotFoundError(f"Memory file not found: {path}")

        try:
            with open(content_file, "r", encoding="utf-8") as f:
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

        Creates node directory if it doesn't exist, then writes to .content file.
        """
        node_path = self._validate_path(path)
        content_file = self._get_content_file_path(node_path)

        # Create node directory if it doesn't exist
        node_path.mkdir(parents=True, exist_ok=True)

        try:
            # Write to temporary file first
            fd, temp_path = tempfile.mkstemp(
                dir=node_path,
                prefix=f".{self.CONTENT_FILENAME}.",
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
                os.replace(temp_path, content_file)
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
        """Check if memory node exists (has a .content file)."""
        try:
            node_path = self._validate_path(path)
            content_file = self._get_content_file_path(node_path)
            return content_file.exists() and content_file.is_file()
        except MemoryInvalidPathError:
            return False

    def list_files(self) -> List[str]:
        """
        List all memory file paths recursively.

        Returns relative paths to nodes (not .content files), excluding metadata directory.
        """
        nodes = []

        for content_file in self.base_path.rglob(self.CONTENT_FILENAME):
            # Skip metadata directory
            try:
                content_file.relative_to(self.metadata_path)
                continue  # This is in metadata dir, skip it
            except ValueError:
                pass  # Not in metadata dir, keep it

            # Get the node directory path (parent of .content file)
            node_dir = content_file.parent
            rel_path = node_dir.relative_to(self.base_path)

            # Convert to string, handle root case
            if str(rel_path) == ".":
                continue  # Skip if somehow at root

            nodes.append(str(rel_path).replace("\\", "/"))

        return sorted(nodes)

    def delete(self, path: str) -> None:
        """
        Delete memory node.

        Removes the .content file. The directory is left in place in case
        it has children, which allows for partial deletion.
        """
        node_path = self._validate_path(path)
        content_file = self._get_content_file_path(node_path)

        if not content_file.exists():
            raise MemoryNotFoundError(f"Memory file not found: {path}")

        try:
            content_file.unlink()

            # Try to remove directory if it's now empty
            try:
                node_path.rmdir()
            except OSError:
                # Directory not empty (has children), leave it
                pass
        except Exception as e:
            raise MemoryStorageError(f"Failed to delete {path}: {e}")

    def get_size(self, path: str) -> int:
        """Get content file size in bytes."""
        node_path = self._validate_path(path)
        content_file = self._get_content_file_path(node_path)

        if not content_file.exists():
            raise MemoryNotFoundError(f"Memory file not found: {path}")

        try:
            return content_file.stat().st_size
        except Exception as e:
            raise MemoryStorageError(f"Failed to get size of {path}: {e}")

    def get_modified_time(self, path: str) -> datetime:
        """Get last modified timestamp of content file."""
        node_path = self._validate_path(path)
        content_file = self._get_content_file_path(node_path)

        if not content_file.exists():
            raise MemoryNotFoundError(f"Memory file not found: {path}")

        try:
            timestamp = content_file.stat().st_mtime
            return datetime.fromtimestamp(timestamp)
        except Exception as e:
            raise MemoryStorageError(f"Failed to get modified time of {path}: {e}")
