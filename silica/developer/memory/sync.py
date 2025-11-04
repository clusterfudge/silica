"""Sync engine for memory proxy.

This module provides bi-directional synchronization between local persona files
and remote storage via the memory proxy.

Components:
- LocalIndex: Track local vs remote state
- SyncOperationLog: Transaction log for all operations
- ConflictResolver: LLM-based conflict resolution
- SyncEngine: Orchestrate sync operations
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from silica.developer.memory.proxy_client import FileMetadata

logger = logging.getLogger(__name__)


class LocalIndex:
    """Track local filesystem state vs remote state for sync.

    The local index stores the last known state of remote files,
    allowing us to detect changes and conflicts.

    Stored as: <persona_base_dir>/.sync-index.json
    """

    def __init__(self, base_dir: Path):
        """Initialize local index.

        Args:
            base_dir: Base directory for persona (e.g., ~/.silica/personas/default)
        """
        self.base_dir = Path(base_dir)
        self.index_file = self.base_dir / ".sync-index.json"
        self._index: dict[str, FileMetadata] = {}
        self._loaded = False

    def load(self) -> dict[str, FileMetadata]:
        """Load index from disk.

        Returns:
            Dictionary mapping file paths to metadata
        """
        if not self.index_file.exists():
            logger.debug(f"No local index found at {self.index_file}")
            self._index = {}
            self._loaded = True
            return self._index

        try:
            with open(self.index_file, "r") as f:
                data = json.load(f)

            # Convert dict to FileMetadata objects
            self._index = {}
            for path, metadata_dict in data.get("files", {}).items():
                # Parse datetime string
                metadata_dict["last_modified"] = datetime.fromisoformat(
                    metadata_dict["last_modified"]
                )
                self._index[path] = FileMetadata(**metadata_dict)

            self._loaded = True
            logger.debug(f"Loaded local index with {len(self._index)} entries")
            return self._index

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to load local index: {e}")
            self._index = {}
            self._loaded = True
            return self._index

    def save(self) -> None:
        """Save index to disk."""
        # Ensure directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Convert FileMetadata objects to dicts
        data = {
            "files": {
                path: {
                    "md5": metadata.md5,
                    "last_modified": metadata.last_modified.isoformat(),
                    "size": metadata.size,
                    "version": metadata.version,
                    "is_deleted": metadata.is_deleted,
                }
                for path, metadata in self._index.items()
            },
            "index_version": int(datetime.now(timezone.utc).timestamp() * 1000),
            "index_last_modified": datetime.now(timezone.utc).isoformat(),
        }

        try:
            with open(self.index_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved local index with {len(self._index)} entries")
        except OSError as e:
            logger.error(f"Failed to save local index: {e}")
            raise

    def update_entry(self, path: str, metadata: FileMetadata) -> None:
        """Update a single entry in the index.

        Args:
            path: File path
            metadata: File metadata
        """
        if not self._loaded:
            self.load()

        self._index[path] = metadata
        logger.debug(f"Updated index entry: {path} (v{metadata.version})")

    def remove_entry(self, path: str) -> None:
        """Remove an entry from the index.

        Args:
            path: File path to remove
        """
        if not self._loaded:
            self.load()

        if path in self._index:
            del self._index[path]
            logger.debug(f"Removed index entry: {path}")

    def get_entry(self, path: str) -> FileMetadata | None:
        """Get metadata for a file.

        Args:
            path: File path

        Returns:
            FileMetadata if exists, None otherwise
        """
        if not self._loaded:
            self.load()

        return self._index.get(path)

    def get_all_entries(self) -> dict[str, FileMetadata]:
        """Get all entries in the index.

        Returns:
            Dictionary mapping paths to metadata
        """
        if not self._loaded:
            self.load()

        return self._index.copy()

    def clear(self) -> None:
        """Clear all entries from the index."""
        self._index = {}
        self._loaded = True
        logger.debug("Cleared local index")


@dataclass
class SyncOperation:
    """Record of a sync operation."""

    op_id: str
    op_type: str  # "upload", "download", "delete"
    path: str
    status: str  # "success", "failed", "conflict"
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class SyncOperationLog:
    """Transaction log for all sync operations.

    Stores operations in append-only JSONL format for easy debugging
    and recovery from failures.

    Stored as: <persona_base_dir>/.sync-log.jsonl
    """

    def __init__(self, base_dir: Path):
        """Initialize sync operation log.

        Args:
            base_dir: Base directory for persona
        """
        self.base_dir = Path(base_dir)
        self.log_file = self.base_dir / ".sync-log.jsonl"

    def log_operation(
        self,
        op_type: str,
        path: str,
        status: str,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Log a sync operation.

        Args:
            op_type: Operation type ("upload", "download", "delete")
            path: File path
            status: Operation status ("success", "failed", "conflict")
            error: Error message if failed
            metadata: Additional metadata

        Returns:
            Operation ID
        """
        # Ensure directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Generate operation ID
        timestamp = datetime.now(timezone.utc)
        op_id = f"{int(timestamp.timestamp() * 1000)}_{hashlib.md5(path.encode()).hexdigest()[:8]}"

        operation = SyncOperation(
            op_id=op_id,
            op_type=op_type,
            path=path,
            status=status,
            error=error,
            timestamp=timestamp,
            metadata=metadata or {},
        )

        # Append to log file
        try:
            with open(self.log_file, "a") as f:
                log_entry = {
                    "op_id": operation.op_id,
                    "op_type": operation.op_type,
                    "path": operation.path,
                    "status": operation.status,
                    "error": operation.error,
                    "timestamp": operation.timestamp.isoformat(),
                    "metadata": operation.metadata,
                }
                f.write(json.dumps(log_entry) + "\n")

            logger.debug(f"Logged {op_type} operation: {path} ({status})")
            return op_id

        except OSError as e:
            logger.error(f"Failed to write to operation log: {e}")
            raise

    def get_failed_operations(self) -> list[SyncOperation]:
        """Get all failed operations.

        Returns:
            List of failed operations
        """
        return self._filter_operations(lambda op: op.status == "failed")

    def get_recent_operations(self, limit: int = 50) -> list[SyncOperation]:
        """Get recent operations.

        Args:
            limit: Maximum number of operations to return

        Returns:
            List of recent operations (newest first)
        """
        operations = self._read_all_operations()
        return operations[-limit:][::-1]  # Last N, reversed

    def get_operations_for_path(self, path: str) -> list[SyncOperation]:
        """Get all operations for a specific path.

        Args:
            path: File path

        Returns:
            List of operations for this path
        """
        return self._filter_operations(lambda op: op.path == path)

    def clear_operation(self, op_id: str) -> None:
        """Mark an operation as resolved by removing it from active failures.

        Note: This doesn't actually remove from the log (append-only),
        but we can mark it as resolved in a separate index if needed.

        Args:
            op_id: Operation ID to clear
        """
        # For now, this is a no-op since we have append-only log
        # In the future, we could maintain a separate "resolved" index
        logger.debug(f"Operation marked as resolved: {op_id}")

    def _read_all_operations(self) -> list[SyncOperation]:
        """Read all operations from the log.

        Returns:
            List of all operations
        """
        if not self.log_file.exists():
            return []

        operations = []
        try:
            with open(self.log_file, "r") as f:
                for line in f:
                    if not line.strip():
                        continue

                    try:
                        entry = json.loads(line)
                        operation = SyncOperation(
                            op_id=entry["op_id"],
                            op_type=entry["op_type"],
                            path=entry["path"],
                            status=entry["status"],
                            error=entry.get("error"),
                            timestamp=datetime.fromisoformat(entry["timestamp"]),
                            metadata=entry.get("metadata", {}),
                        )
                        operations.append(operation)
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"Skipping invalid log entry: {e}")
                        continue

            return operations

        except OSError as e:
            logger.error(f"Failed to read operation log: {e}")
            return []

    def _filter_operations(self, predicate: callable) -> list[SyncOperation]:
        """Filter operations by predicate.

        Args:
            predicate: Function that takes SyncOperation and returns bool

        Returns:
            List of matching operations
        """
        operations = self._read_all_operations()
        return [op for op in operations if predicate(op)]

    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about sync operations.

        Returns:
            Dictionary with operation statistics
        """
        operations = self._read_all_operations()

        stats = {
            "total_operations": len(operations),
            "by_type": {},
            "by_status": {},
            "recent_failures": 0,
        }

        # Count by type and status
        for op in operations:
            stats["by_type"][op.op_type] = stats["by_type"].get(op.op_type, 0) + 1
            stats["by_status"][op.status] = stats["by_status"].get(op.status, 0) + 1

        # Count recent failures (last 24 hours)
        recent_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
        stats["recent_failures"] = sum(
            1
            for op in operations
            if op.status == "failed" and op.timestamp > recent_threshold
        )

        return stats


# Import needed for timedelta
