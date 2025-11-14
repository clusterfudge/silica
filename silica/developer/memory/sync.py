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

from silica.developer.memory.proxy_client import (
    FileMetadata,
    MemoryProxyClient,
    VersionConflictError,
    NotFoundError,
)
from silica.developer.memory.conflict_resolver import (
    ConflictResolver,
    ConflictResolutionError,
)

logger = logging.getLogger(__name__)


@dataclass
class SyncOperationDetail:
    """Details about a single sync operation."""

    type: str  # "upload", "download", "delete_local", "delete_remote"
    path: str
    reason: str
    local_md5: str | None = None
    remote_md5: str | None = None
    local_version: int | None = None
    remote_version: int | None = None
    local_size: int | None = None
    remote_size: int | None = None


@dataclass
class SyncPlan:
    """Plan for sync operations."""

    upload: list[SyncOperationDetail] = field(default_factory=list)
    download: list[SyncOperationDetail] = field(default_factory=list)
    delete_local: list[SyncOperationDetail] = field(default_factory=list)
    delete_remote: list[SyncOperationDetail] = field(default_factory=list)
    conflicts: list[SyncOperationDetail] = field(default_factory=list)

    @property
    def total_operations(self) -> int:
        """Get total number of operations in plan."""
        return (
            len(self.upload)
            + len(self.download)
            + len(self.delete_local)
            + len(self.delete_remote)
        )

    @property
    def has_conflicts(self) -> bool:
        """Check if plan has any conflicts."""
        return len(self.conflicts) > 0


@dataclass
class SyncResult:
    """Result of sync execution."""

    succeeded: list[SyncOperationDetail] = field(default_factory=list)
    failed: list[SyncOperationDetail] = field(default_factory=list)
    conflicts: list[SyncOperationDetail] = field(default_factory=list)
    skipped: list[SyncOperationDetail] = field(default_factory=list)
    duration: float = 0.0

    @property
    def total(self) -> int:
        """Get total number of operations attempted."""
        return (
            len(self.succeeded)
            + len(self.failed)
            + len(self.conflicts)
            + len(self.skipped)
        )

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total == 0:
            return 100.0
        return (len(self.succeeded) / self.total) * 100.0


@dataclass
class SyncStatus:
    """Current sync status for status command."""

    in_sync: list[str] = field(default_factory=list)
    pending_upload: list[dict] = field(default_factory=list)
    pending_download: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    last_sync: datetime | None = None

    @property
    def needs_sync(self) -> bool:
        """Check if any action is needed."""
        return bool(
            self.pending_upload
            or self.pending_download
            or self.failed
            or self.conflicts
        )


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

    def _filter_operations(self, predicate: callable) -> list[SyncOperation]:
        """Filter operations by predicate.

        Args:
            predicate: Function that takes SyncOperation and returns bool

        Returns:
            List of matching operations
        """
        operations = self._read_all_operations()
        return [op for op in operations if predicate(op)]

    def truncate_after_sync(self, keep_days: int = 7) -> int:
        """Truncate log after successful sync.

        Strategy:
        - Keep all failed operations (for retry)
        - Keep successful operations from last N days (for debugging)
        - Remove old successful operations

        Args:
            keep_days: Number of days of successful operations to keep

        Returns:
            Number of operations removed
        """
        if not self.log_file.exists():
            return 0

        operations = self._read_all_operations()
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)

        # Keep: failed operations OR recent successful operations
        kept_operations = [
            op for op in operations if op.status != "success" or op.timestamp > cutoff
        ]

        removed_count = len(operations) - len(kept_operations)

        if removed_count > 0:
            # Rewrite log file with kept operations only
            try:
                with open(self.log_file, "w") as f:
                    for op in kept_operations:
                        log_entry = {
                            "op_id": op.op_id,
                            "op_type": op.op_type,
                            "path": op.path,
                            "status": op.status,
                            "error": op.error,
                            "timestamp": op.timestamp.isoformat(),
                            "metadata": op.metadata,
                        }
                        f.write(json.dumps(log_entry) + "\n")

                logger.info(
                    f"Truncated operation log: removed {removed_count} old successful operations"
                )
            except OSError as e:
                logger.error(f"Failed to truncate operation log: {e}")
                raise

        return removed_count


@dataclass
class FileInfo:
    """Information about a local file."""

    path: str
    md5: str
    size: int
    last_modified: datetime


class SyncEngine:
    """Orchestrate sync operations between local and remote storage.

    The sync engine analyzes the differences between local files, the local index
    (which tracks the last known remote state), and the actual remote state to
    determine what operations need to be performed.
    """

    def __init__(
        self,
        client: MemoryProxyClient,
        local_base_dir: Path,
        namespace: str,
        conflict_resolver: ConflictResolver | None = None,
        scan_base: Path | None = None,
    ):
        """Initialize sync engine.

        Args:
            client: Memory proxy client
            local_base_dir: Base directory for persona (e.g., ~/.silica/personas/default)
            namespace: Namespace for remote storage (e.g., "default/memory")
            conflict_resolver: Conflict resolver for handling merge conflicts (optional)
            scan_base: Base directory to scan files from (default: local_base_dir)
                      Used for namespace-specific scanning (e.g., memory/ or history/session/)
        """
        self.client = client
        self.local_base_dir = Path(local_base_dir)
        self.namespace = namespace
        self.conflict_resolver = conflict_resolver
        self.scan_base = Path(scan_base) if scan_base else self.local_base_dir

        self.local_index = LocalIndex(local_base_dir)
        self.operation_log = SyncOperationLog(local_base_dir)

    def analyze_sync_operations(self) -> SyncPlan:
        """Analyze local vs remote and create sync plan.

        This method compares:
        1. Local filesystem state
        2. Local index (last known remote state)
        3. Current remote state

        Returns:
            SyncPlan with operations to perform
        """
        plan = SyncPlan()

        # Load local index
        self.local_index.load()

        # Scan local files
        local_files = self._scan_local_files()

        # Get remote index
        try:
            remote_index_response = self.client.get_sync_index(self.namespace)
        except Exception as e:
            logger.error(f"Failed to get remote index: {e}")
            # If we can't get remote index, we can't sync
            raise

        # Convert remote index (SyncIndexResponse) to dict for easier lookup
        # remote_index_response.files is a dict[str, FileMetadata]
        remote_files = remote_index_response.files

        # Get all unique paths
        all_paths = set(local_files.keys()) | set(remote_files.keys())

        for path in all_paths:
            local_file = local_files.get(path)
            remote_entry = remote_files.get(path)
            index_entry = self.local_index.get_entry(path)

            # Determine what operation is needed
            op = self._determine_operation(path, local_file, remote_entry, index_entry)

            if op:
                if op.type == "upload":
                    plan.upload.append(op)
                elif op.type == "download":
                    plan.download.append(op)
                elif op.type == "delete_local":
                    plan.delete_local.append(op)
                elif op.type == "delete_remote":
                    plan.delete_remote.append(op)
                elif op.type == "conflict":
                    plan.conflicts.append(op)

        return plan

    def resolve_conflicts(
        self, conflicts: list[SyncOperationDetail]
    ) -> list[SyncOperationDetail]:
        """Resolve all conflicts using configured conflict resolver.

        This method:
        1. Downloads remote content for each conflict
        2. Reads local content
        3. Calls conflict resolver to merge
        4. Writes merged content locally
        5. Returns upload operations for merged files

        Args:
            conflicts: List of conflict operations

        Returns:
            List of upload operations for resolved (merged) files

        Raises:
            ValueError: If no conflict resolver configured
            ConflictResolutionError: If conflict resolution fails
        """
        if not self.conflict_resolver:
            raise ValueError(
                "No conflict resolver configured. "
                "Cannot resolve conflicts without a resolver."
            )

        if not conflicts:
            return []

        logger.info(f"Resolving {len(conflicts)} conflicts")
        resolved_uploads = []

        for conflict in conflicts:
            try:
                # Get local content
                local_path = self.local_base_dir / conflict.path
                if not local_path.exists():
                    logger.warning(
                        f"Local file missing during conflict resolution: {conflict.path}"
                    )
                    continue

                local_content = local_path.read_bytes()

                # Get remote content
                remote_content, md5, last_mod, content_type, version = (
                    self.client.read_blob(
                        namespace=self.namespace,
                        path=conflict.path,
                    )
                )

                logger.debug(
                    f"Resolving conflict for {conflict.path}: "
                    f"local={len(local_content)} bytes, remote={len(remote_content)} bytes"
                )

                # Get file metadata for LLM context
                local_metadata = {"path": str(local_path)}
                if local_path.exists():
                    local_metadata["mtime"] = local_path.stat().st_mtime

                remote_metadata = {
                    "last_modified": last_mod.isoformat() if last_mod else None,
                    "version": version,
                    "md5": md5,
                }

                # Resolve conflict using LLM
                merged_content = self.conflict_resolver.resolve_conflict(
                    path=conflict.path,
                    local_content=local_content,
                    remote_content=remote_content,
                    local_metadata=local_metadata,
                    remote_metadata=remote_metadata,
                )

                # Write merged content locally
                local_path.write_bytes(merged_content)

                logger.info(
                    f"Resolved conflict for {conflict.path}, "
                    f"merged={len(merged_content)} bytes"
                )

                # Create upload operation for merged file
                # Use remote version as expected_version since we just read it
                resolved_uploads.append(
                    SyncOperationDetail(
                        type="upload",
                        path=conflict.path,
                        reason="Conflict resolved via LLM merge",
                        remote_version=version,
                    )
                )

            except Exception as e:
                logger.error(f"Failed to resolve conflict for {conflict.path}: {e}")
                raise ConflictResolutionError(
                    f"Failed to resolve conflict for {conflict.path}: {e}"
                ) from e

        logger.info(
            f"Successfully resolved {len(resolved_uploads)} conflicts, "
            f"ready for upload"
        )
        return resolved_uploads

    def _determine_operation(
        self,
        path: str,
        local_file: FileInfo | None,
        remote_entry: FileMetadata | None,
        index_entry: FileMetadata | None,
    ) -> SyncOperationDetail | None:
        """Determine what operation is needed for a file (simplified version-based logic).

        This uses a version-based approach:
        - remote.version > index.version means remote changed
        - local.md5 != index.md5 means local changed
        - If both changed → CONFLICT (resolve via LLM)
        - If only one changed → sync that direction
        - If neither changed → IN SYNC

        Args:
            path: File path
            local_file: Local file info (None if doesn't exist)
            remote_entry: Remote metadata (None if doesn't exist)
            index_entry: Last known remote state (None if never synced)

        Returns:
            SyncOperationDetail if an operation is needed, None if in sync
        """
        # Determine what changed using version-based comparison
        local_changed = False
        remote_changed = False

        if local_file and index_entry:
            # Local changed if MD5 differs from last known state
            local_changed = local_file.md5 != index_entry.md5

        if remote_entry and index_entry:
            # Remote changed if version increased
            remote_changed = remote_entry.version > index_entry.version

        # Case 1: File exists locally and remotely
        if local_file and remote_entry:
            # Handle tombstones (deleted on remote but still in index)
            if remote_entry.is_deleted:
                if index_entry and not index_entry.is_deleted:
                    # Remote was deleted after we last synced
                    return SyncOperationDetail(
                        type="delete_local",
                        path=path,
                        reason="Deleted remotely",
                        remote_version=remote_entry.version,
                    )
                else:
                    # Conflict: local file exists but remote shows deleted
                    return SyncOperationDetail(
                        type="conflict",
                        path=path,
                        reason="Local file exists but remote is deleted",
                        local_md5=local_file.md5,
                        remote_version=remote_entry.version,
                    )

            # Files match - in sync
            if local_file.md5 == remote_entry.md5:
                # Update index to track current state
                # Use local file's mtime for optimization, but remote version/deleted status
                self.local_index.update_entry(
                    path,
                    FileMetadata(
                        md5=local_file.md5,
                        last_modified=local_file.last_modified,  # Use local mtime!
                        size=local_file.size,
                        version=remote_entry.version,
                        is_deleted=False,
                    ),
                )
                return None  # In sync

            # Files differ - determine action based on what changed
            if local_changed and remote_changed:
                # CONFLICT: Both sides modified since last sync
                return SyncOperationDetail(
                    type="conflict",
                    path=path,
                    reason="Both local and remote modified since last sync",
                    local_md5=local_file.md5,
                    remote_md5=remote_entry.md5,
                    local_version=index_entry.version if index_entry else None,
                    remote_version=remote_entry.version,
                )

            elif local_changed:
                # Only local changed - upload
                return SyncOperationDetail(
                    type="upload",
                    path=path,
                    reason="Local file modified",
                    local_md5=local_file.md5,
                    remote_version=remote_entry.version,
                )

            elif remote_changed:
                # Only remote changed - download
                return SyncOperationDetail(
                    type="download",
                    path=path,
                    reason="Remote file modified",
                    remote_md5=remote_entry.md5,
                    remote_version=remote_entry.version,
                )

            else:
                # Neither changed according to our tracking, but files differ
                # This shouldn't happen if our index is consistent
                # Treat as conflict to be safe
                return SyncOperationDetail(
                    type="conflict",
                    path=path,
                    reason="Files differ with no recorded changes (index may be stale)",
                    local_md5=local_file.md5,
                    remote_md5=remote_entry.md5,
                )

        # Case 2: File only exists locally
        elif local_file and not remote_entry:
            if index_entry and not index_entry.is_deleted:
                # We knew about this file remotely before - it was deleted remotely
                return SyncOperationDetail(
                    type="delete_local",
                    path=path,
                    reason="Deleted remotely",
                    local_md5=local_file.md5,
                )
            else:
                # New local file - upload it
                return SyncOperationDetail(
                    type="upload",
                    path=path,
                    reason="New local file",
                    local_md5=local_file.md5,
                    local_size=local_file.size,
                )

        # Case 3: File only exists remotely
        elif not local_file and remote_entry:
            remote_deleted = remote_entry.is_deleted

            if remote_deleted:
                # Remote tombstone only - nothing to do
                return None

            if index_entry:
                # We knew about this file - local was deleted
                return SyncOperationDetail(
                    type="delete_remote",
                    path=path,
                    reason="Deleted locally",
                    remote_md5=remote_entry.md5,
                    remote_version=remote_entry.version,
                )
            else:
                # New remote file - download it
                return SyncOperationDetail(
                    type="download",
                    path=path,
                    reason="New remote file",
                    remote_md5=remote_entry.md5,
                    remote_size=remote_entry.size,
                    remote_version=remote_entry.version,
                )

        # Case 4: File exists in neither place (shouldn't happen)
        return None

    def execute_sync(
        self,
        plan: SyncPlan,
        show_progress: bool = True,
    ) -> SyncResult:
        """Execute sync plan.

        Conflicts must be resolved before calling this method.
        If any conflicts remain in the plan, this will raise an error.

        Args:
            plan: Sync plan to execute (must not have conflicts)
            show_progress: Whether to show progress (requires rich)

        Returns:
            SyncResult with operation results

        Raises:
            ValueError: If plan contains unresolved conflicts
        """
        import time

        start_time = time.time()
        result = SyncResult()

        # FAIL if there are unresolved conflicts
        if plan.conflicts:
            raise ValueError(
                f"Cannot execute sync with {len(plan.conflicts)} unresolved conflicts. "
                f"Conflicts must be resolved before execution. "
                f"Conflicting files: {[c.path for c in plan.conflicts]}"
            )

        # Set up progress bar if requested
        progress_bar = None
        task_id = None
        total_ops = plan.total_operations

        if show_progress and total_ops > 0:
            try:
                from rich.progress import (
                    Progress,
                    SpinnerColumn,
                    BarColumn,
                    TextColumn,
                    TimeRemainingColumn,
                )

                progress_bar = Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TextColumn("({task.completed}/{task.total})"),
                    TimeRemainingColumn(),
                )
                progress_bar.start()
                task_id = progress_bar.add_task(
                    "[cyan]Syncing files...", total=total_ops
                )
            except ImportError:
                # rich not available, continue without progress
                pass

        try:
            # Execute uploads
            for op in plan.upload:
                try:
                    success = self.upload_file(op.path, op.remote_version or 0)
                    if success:
                        result.succeeded.append(op)
                    else:
                        result.failed.append(op)
                except Exception as e:
                    logger.error(f"Upload failed for {op.path}: {e}")
                    result.failed.append(op)
                    self.operation_log.log_operation(
                        "upload", op.path, "failed", error=str(e)
                    )
                finally:
                    if progress_bar and task_id is not None:
                        progress_bar.update(task_id, advance=1)

            # Execute downloads
            for op in plan.download:
                try:
                    success = self.download_file(op.path)
                    if success:
                        result.succeeded.append(op)
                    else:
                        result.failed.append(op)
                except Exception as e:
                    logger.error(f"Download failed for {op.path}: {e}")
                    result.failed.append(op)
                    self.operation_log.log_operation(
                        "download", op.path, "failed", error=str(e)
                    )
                finally:
                    if progress_bar and task_id is not None:
                        progress_bar.update(task_id, advance=1)

            # Execute local deletes
            for op in plan.delete_local:
                try:
                    success = self.delete_local(op.path)
                    if success:
                        result.succeeded.append(op)
                    else:
                        result.failed.append(op)
                except Exception as e:
                    logger.error(f"Delete local failed for {op.path}: {e}")
                    result.failed.append(op)
                    self.operation_log.log_operation(
                        "delete_local", op.path, "failed", error=str(e)
                    )
                finally:
                    if progress_bar and task_id is not None:
                        progress_bar.update(task_id, advance=1)

            # Execute remote deletes
            for op in plan.delete_remote:
                try:
                    success = self.delete_remote(op.path, op.remote_version or 0)
                    if success:
                        result.succeeded.append(op)
                    else:
                        result.failed.append(op)
                except Exception as e:
                    logger.error(f"Delete remote failed for {op.path}: {e}")
                    result.failed.append(op)
                    self.operation_log.log_operation(
                        "delete_remote", op.path, "failed", error=str(e)
                    )
                finally:
                    if progress_bar and task_id is not None:
                        progress_bar.update(task_id, advance=1)

            result.duration = time.time() - start_time

            # Save updated index
            self.local_index.save()

            return result
        finally:
            # Clean up progress bar
            if progress_bar:
                progress_bar.stop()

    def upload_file(self, path: str, remote_version: int) -> bool:
        """Upload file to remote with conditional write.

        Args:
            path: File path relative to scan_base directory
            remote_version: Expected remote version (0 for new files)

        Returns:
            True if successful, False otherwise
        """
        full_path = self.scan_base / path

        if not full_path.exists():
            logger.error(f"Cannot upload {path}: file not found")
            return False

        try:
            # Read file content
            with open(full_path, "rb") as f:
                content = f.read()

            # Calculate MD5
            md5 = self._calculate_md5(content)

            # Upload to remote
            # write_blob returns tuple (is_new, md5, version)
            is_new, returned_md5, new_version = self.client.write_blob(
                namespace=self.namespace,
                path=path,
                content=content,
                expected_version=remote_version,
                content_type="application/octet-stream",
            )

            # Get the actual file mtime for index
            file_mtime = datetime.fromtimestamp(
                full_path.stat().st_mtime, tz=timezone.utc
            )

            # Update local index with LOCAL file's mtime (not upload time)
            self.local_index.update_entry(
                path,
                FileMetadata(
                    md5=md5,
                    last_modified=file_mtime,
                    size=len(content),
                    version=new_version,
                    is_deleted=False,
                ),
            )

            # Log success
            self.operation_log.log_operation(
                "upload",
                path,
                "success",
                metadata={"version": new_version, "size": len(content)},
            )

            logger.info(f"Uploaded {path} (v{new_version})")
            return True

        except VersionConflictError as e:
            logger.warning(f"Version conflict uploading {path}: {e}")
            self.operation_log.log_operation("upload", path, "conflict", error=str(e))
            return False
        except Exception as e:
            logger.error(f"Failed to upload {path}: {e}")
            self.operation_log.log_operation("upload", path, "failed", error=str(e))
            return False

    def download_file(self, path: str) -> bool:
        """Download file from remote.

        Args:
            path: File path relative to scan_base directory

        Returns:
            True if successful, False otherwise
        """
        full_path = self.scan_base / path

        try:
            # Download from remote
            # read_blob returns (content, md5, last_modified, content_type, version)
            content, md5, last_modified, content_type, version = self.client.read_blob(
                namespace=self.namespace, path=path
            )

            # Ensure directory exists
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            with open(full_path, "wb") as f:
                f.write(content)

            # Get the actual file mtime after writing
            file_mtime = datetime.fromtimestamp(
                full_path.stat().st_mtime, tz=timezone.utc
            )

            # Create metadata object with LOCAL file's mtime (not remote's)
            file_metadata = FileMetadata(
                md5=md5,
                last_modified=file_mtime,
                size=len(content),
                version=version,
                is_deleted=False,
            )

            # Update local index
            self.local_index.update_entry(path, file_metadata)

            # Log success
            self.operation_log.log_operation(
                "download",
                path,
                "success",
                metadata={"version": version, "size": len(content)},
            )

            logger.info(f"Downloaded {path} (v{version})")
            return True

        except NotFoundError:
            logger.warning(f"File not found remotely: {path}")
            self.operation_log.log_operation(
                "download", path, "failed", error="Not found"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to download {path}: {e}")
            self.operation_log.log_operation("download", path, "failed", error=str(e))
            return False

    def delete_local(self, path: str) -> bool:
        """Delete local file.

        Args:
            path: File path relative to scan_base directory

        Returns:
            True if successful, False otherwise
        """
        full_path = self.scan_base / path

        try:
            if full_path.exists():
                full_path.unlink()

            # Update local index (don't remove, mark as deleted to track remote state)
            index_entry = self.local_index.get_entry(path)
            if index_entry:
                index_entry.is_deleted = True
                self.local_index.update_entry(path, index_entry)

            # Log success
            self.operation_log.log_operation("delete_local", path, "success")

            logger.info(f"Deleted local file {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete local {path}: {e}")
            self.operation_log.log_operation(
                "delete_local", path, "failed", error=str(e)
            )
            return False

    def delete_remote(self, path: str, remote_version: int) -> bool:
        """Delete remote file (create tombstone).

        Args:
            path: File path relative to base directory
            remote_version: Expected remote version

        Returns:
            True if successful, False otherwise
        """
        try:
            # Delete on remote (creates tombstone)
            new_version = self.client.delete_blob(
                namespace=self.namespace,
                path=path,
                expected_version=remote_version,
            )

            # Update local index
            self.local_index.update_entry(
                path,
                FileMetadata(
                    md5="",
                    last_modified=datetime.now(timezone.utc),
                    size=0,
                    version=new_version,
                    is_deleted=True,
                ),
            )

            # Log success
            self.operation_log.log_operation(
                "delete_remote",
                path,
                "success",
                metadata={"version": new_version},
            )

            logger.info(f"Deleted remote file {path} (v{new_version})")
            return True

        except VersionConflictError as e:
            logger.warning(f"Version conflict deleting {path}: {e}")
            self.operation_log.log_operation(
                "delete_remote", path, "conflict", error=str(e)
            )
            return False
        except Exception as e:
            logger.error(f"Failed to delete remote {path}: {e}")
            self.operation_log.log_operation(
                "delete_remote", path, "failed", error=str(e)
            )
            return False

    def get_sync_status(self) -> SyncStatus:
        """Get detailed sync status.

        Returns:
            SyncStatus with current state
        """
        # This would be implemented to check current state
        # For now, return empty status
        return SyncStatus()

    def _scan_local_files(self) -> dict[str, FileInfo]:
        """Scan local filesystem for files to sync.

        Optimized to avoid reading unchanged files by checking mtime against index.
        Scans from scan_base directory (which may be a subdirectory like memory/).

        Returns:
            Dictionary mapping paths to FileInfo (paths relative to scan_base)
        """
        files = {}

        # Helper to process a single file
        def process_file(file_path: Path, rel_path: str):
            try:
                stat_info = file_path.stat()
                file_size = stat_info.st_size
                file_mtime = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc)

                # Check if we have this file in the index
                index_entry = self.local_index.get_entry(rel_path)

                # Fast path: If file hasn't been modified recently and size matches, use cached MD5
                # Only use cache if file is "stable" (mtime > 2 seconds old) to catch rapid edits
                if index_entry and not index_entry.is_deleted:
                    time_since_mod = (
                        datetime.now(timezone.utc) - file_mtime
                    ).total_seconds()
                    mtime_diff = abs(
                        (file_mtime - index_entry.last_modified).total_seconds()
                    )

                    # Use cached MD5 if:
                    # 1. File hasn't been touched in over 2 seconds (stable file)
                    # 2. Size matches index
                    # 3. Mtime matches index (within 1-second tolerance for filesystem precision)
                    if (
                        time_since_mod > 2.0
                        and file_size == index_entry.size
                        and mtime_diff < 1.0
                    ):
                        # File unchanged and stable - use cached MD5
                        files[rel_path] = FileInfo(
                            path=rel_path,
                            md5=index_entry.md5,
                            size=file_size,
                            last_modified=file_mtime,
                        )
                        return

                # Slow path: File changed or not in index - read and hash
                with open(file_path, "rb") as f:
                    content = f.read()

                files[rel_path] = FileInfo(
                    path=rel_path,
                    md5=self._calculate_md5(content),
                    size=len(content),
                    last_modified=file_mtime,
                )
            except Exception as e:
                logger.warning(f"Failed to read {rel_path}: {e}")

        # Scan all files recursively from scan_base
        if not self.scan_base.exists():
            # Debug level - this is expected for new sessions before first turn
            logger.debug(f"Scan base directory does not exist: {self.scan_base}")
            return files

        for file_path in self.scan_base.rglob("*"):
            if not file_path.is_file():
                continue

            # Skip sync metadata files
            if file_path.name in [".sync-index.json", ".sync-log.jsonl"]:
                continue

            # Get relative path from scan_base (not local_base_dir!)
            try:
                rel_path = str(file_path.relative_to(self.scan_base))
            except ValueError:
                continue

            process_file(file_path, rel_path)

        return files

    def _calculate_md5(self, content: bytes) -> str:
        """Calculate MD5 hash of content.

        Args:
            content: File content

        Returns:
            MD5 hash as hex string
        """
        return hashlib.md5(content).hexdigest()
