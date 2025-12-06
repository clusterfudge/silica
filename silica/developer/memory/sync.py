"""Sync engine for memory proxy.

This module provides bi-directional synchronization between local persona files
and remote storage via the memory proxy.

Components:
- LocalIndex: Track local vs remote state
- SyncOperationLog: Transaction log for all operations
- ConflictResolver: LLM-based conflict resolution
- SyncEngine: Orchestrate sync operations
"""

import gzip
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from silica.developer.memory.conflict_resolver import (
    ConflictResolver,
    ConflictResolutionError,
)
from silica.developer.memory.md5_cache import MD5Cache
from silica.developer.memory.proxy_client import (
    FileMetadata,
    MemoryProxyClient,
    NotFoundError,
    VersionConflictError,
)

if TYPE_CHECKING:
    from silica.developer.memory.sync_config import SyncConfig

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

    Index file location is now configurable per namespace.
    """

    def __init__(self, index_file: Path):
        """Initialize local index.

        Args:
            index_file: Path to the index file (e.g., ~/.silica/personas/default/.sync-index-memory.json)
        """
        self.index_file = Path(index_file)
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
        self.index_file.parent.mkdir(parents=True, exist_ok=True)

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

    Now supports multiple independent namespaces through SyncConfig.
    """

    def __init__(
        self,
        client: MemoryProxyClient,
        config: "SyncConfig",
        conflict_resolver: ConflictResolver | None = None,
    ):
        """Initialize sync engine.

        Args:
            client: Memory proxy client
            config: Sync configuration (namespace, paths, indices)
            conflict_resolver: Conflict resolver for handling merge conflicts (optional)
        """

        self.client = client
        self.config = config
        self.conflict_resolver = conflict_resolver

        self.local_index = LocalIndex(config.index_file)
        self.md5_cache = MD5Cache()

        # Base directory for file operations (where files are read from/written to)
        self._base_dir = config.base_dir

        # Map sync paths to their full local filesystem paths
        # Since paths in sync are relative to scan_paths, we need this mapping
        # to find files during upload/download operations
        self._path_to_full_path: dict[str, Path] = {}

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
            remote_index_response = self.client.get_sync_index(self.config.namespace)
        except Exception as e:
            logger.error(f"Failed to get remote index: {e}")
            # If we can't get remote index, we can't sync
            raise

        # Convert remote index (SyncIndexResponse) to dict for easier lookup
        # remote_index_response.files is a dict[str, FileMetadata]
        remote_files = remote_index_response.files

        # Build path mappings for compression support
        # When compression is enabled, local "foo.json" maps to remote "foo.json.gz"
        local_to_remote: dict[str, str] = {}
        remote_to_local: dict[str, str] = {}

        for local_path in local_files.keys():
            if self.config.compress:
                remote_path = f"{local_path}.gz"
            else:
                remote_path = local_path
            local_to_remote[local_path] = remote_path
            remote_to_local[remote_path] = local_path

        # Also map any remote .gz files to their local counterparts
        for remote_path in remote_files.keys():
            if remote_path.endswith(".gz"):
                local_path = remote_path[:-3]
                if local_path not in local_to_remote:
                    local_to_remote[local_path] = remote_path
                remote_to_local[remote_path] = local_path
            elif remote_path not in remote_to_local:
                remote_to_local[remote_path] = remote_path
                if remote_path not in local_to_remote:
                    local_to_remote[remote_path] = remote_path

        # Get all unique LOCAL paths (we work in local path space)
        all_local_paths = set(local_files.keys()) | set(remote_to_local.values())

        for local_path in all_local_paths:
            local_file = local_files.get(local_path)

            # Find corresponding remote path (may be .gz version)
            remote_path = local_to_remote.get(local_path, local_path)
            # Also check for non-.gz version if .gz not found
            remote_entry = remote_files.get(remote_path)
            if remote_entry is None and self.config.compress:
                # Maybe remote doesn't have .gz yet, check uncompressed
                remote_entry = remote_files.get(local_path)
                if remote_entry is not None:
                    remote_path = local_path

            # Index may track either compressed or uncompressed path
            index_entry = self.local_index.get_entry(remote_path)
            if index_entry is None:
                index_entry = self.local_index.get_entry(local_path)

            # Determine what operation is needed
            # Pass local_path for file operations, remote_path for remote operations
            op = self._determine_operation(
                local_path, local_file, remote_entry, index_entry, remote_path
            )

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
                # Look up full path from mapping (built during scan)
                local_path = self._path_to_full_path.get(conflict.path)
                if not local_path:
                    # Fallback for backward compatibility
                    local_path = self._base_dir / conflict.path
                if not local_path.exists():
                    logger.warning(
                        f"Local file missing during conflict resolution: {conflict.path}"
                    )
                    continue

                local_content = local_path.read_bytes()

                # Get remote content
                remote_content, md5, last_mod, content_type, version = (
                    self.client.read_blob(
                        namespace=self.config.namespace,
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
            f"Successfully resolved {len(resolved_uploads)} conflicts, ready for upload"
        )
        return resolved_uploads

    def _determine_operation(
        self,
        path: str,
        local_file: FileInfo | None,
        remote_entry: FileMetadata | None,
        index_entry: FileMetadata | None,
        remote_path: str | None = None,
    ) -> SyncOperationDetail | None:
        """Determine what operation is needed for a file.

        **Core Principle**: Remote is authoritative, local is cache.
        Only explicit tombstones (remote_entry.is_deleted == True) trigger local deletion.

        Decision logic:
        1. Check for remote tombstone → delete local (explicit deletion)
        2. Check existence patterns and apply rules:
           - Local exists, remote missing → UPLOAD (preserve local work)
           - Local missing, remote exists → DOWNLOAD or DELETE_REMOTE
           - Both exist → Compare versions for sync direction
           - Neither exists → No operation

        Args:
            path: Local file path
            local_file: Local file info (None if doesn't exist)
            remote_entry: Remote metadata (None if doesn't exist)
            index_entry: Last known remote state (None if never synced)
            remote_path: Remote file path (may differ from local if compressed)

        Returns:
            SyncOperationDetail if an operation is needed, None if in sync
        """
        # Use remote_path for operations if provided, otherwise use local path
        effective_remote_path = remote_path if remote_path else path
        # ==========================================
        # STEP 1: Check for explicit tombstone
        # ==========================================
        # Tombstones are the ONLY way to trigger local file deletion.
        # They are unambiguous and always honored.

        if remote_entry and remote_entry.is_deleted:
            # Explicit tombstone in remote index
            if local_file:
                # Local file exists, remote has tombstone → delete local
                return SyncOperationDetail(
                    type="delete_local",
                    path=path,  # Use local path for delete_local
                    reason="Explicit remote deletion (tombstone)",
                    local_md5=local_file.md5,
                    remote_version=remote_entry.version,
                )
            else:
                # Local already deleted, just update index to track tombstone
                if index_entry and not index_entry.is_deleted:
                    # Update our index to reflect the tombstone
                    self.local_index.update_entry(effective_remote_path, remote_entry)
                return None  # No operation needed

        # ==========================================
        # STEP 2: Handle existence patterns
        # ==========================================

        # CASE A: Both local and remote exist
        if local_file and remote_entry:
            # Files match - in sync
            if local_file.md5 == remote_entry.md5:
                # Update index to track current state (use remote path for index)
                self.local_index.update_entry(effective_remote_path, remote_entry)
                return None  # In sync

            # Files differ - determine sync direction

            # Bootstrap scenario: no index entry means we don't know history
            if not index_entry:
                # Remote is authority on bootstrap - download remote version
                return SyncOperationDetail(
                    type="download",
                    path=effective_remote_path,
                    reason="Remote is authority, bootstrap scenario",
                    remote_md5=remote_entry.md5,
                    remote_version=remote_entry.version,
                )

            # We have history - determine what changed
            local_changed = local_file.md5 != index_entry.md5
            remote_changed = remote_entry.version > index_entry.version

            if local_changed and remote_changed:
                # CONFLICT: Both sides modified since last sync
                return SyncOperationDetail(
                    type="conflict",
                    path=path,
                    reason="Both local and remote modified since last sync",
                    local_md5=local_file.md5,
                    remote_md5=remote_entry.md5,
                    local_version=index_entry.version,
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
                    path=effective_remote_path,
                    reason="Remote file modified",
                    remote_md5=remote_entry.md5,
                    remote_version=remote_entry.version,
                )

            else:
                # Neither changed according to index, but files differ
                # Index may be stale - treat as conflict to be safe
                return SyncOperationDetail(
                    type="conflict",
                    path=path,
                    reason="Files differ with no recorded changes (index may be stale)",
                    local_md5=local_file.md5,
                    remote_md5=remote_entry.md5,
                )

        # CASE B: Only local file exists (remote is missing)
        elif local_file and not remote_entry:
            # CRITICAL FIX: Missing remote entry does NOT imply deletion!
            # It could mean:
            # - New local file (never synced)
            # - Remote namespace was reset
            # - File was re-created after deletion
            # - Bootstrap scenario with old index
            #
            # SAFE DEFAULT: Upload the local file (preserves user work)
            # We only delete local files with explicit tombstones.

            if index_entry:
                # We have history - file was known before
                # Upload to restore/re-create on remote
                # NOTE: Use version 0 because remote doesn't have the file anymore.
                # The old index version is stale and would cause a version conflict.
                return SyncOperationDetail(
                    type="upload",
                    path=path,
                    reason="Re-upload to remote (missing remote entry, preserving local work)",
                    local_md5=local_file.md5,
                    local_size=local_file.size,
                    remote_version=0,  # New file on remote
                )
            else:
                # No history - new local file
                return SyncOperationDetail(
                    type="upload",
                    path=path,
                    reason="New local file",
                    local_md5=local_file.md5,
                    local_size=local_file.size,
                )

        # CASE C: Only remote file exists (local is missing)
        elif not local_file and remote_entry:
            # Remote exists (and not tombstone, checked in step 1)

            if index_entry:
                # We knew about this file - local was deleted
                # Propagate deletion to remote (create tombstone)
                return SyncOperationDetail(
                    type="delete_remote",
                    path=effective_remote_path,
                    reason="Deleted locally",
                    remote_md5=remote_entry.md5,
                    remote_version=remote_entry.version,
                )
            else:
                # No history - new remote file (bootstrap)
                # Download it
                return SyncOperationDetail(
                    type="download",
                    path=effective_remote_path,
                    reason="New remote file",
                    remote_md5=remote_entry.md5,
                    remote_size=remote_entry.size,
                    remote_version=remote_entry.version,
                )

        # CASE D: Neither local nor remote exists
        # This occurs when:
        # - Both files deleted and tombstone was purged from remote index
        # - Files deleted outside sync system (manual cleanup)
        # - Index recovery/consistency check
        else:
            # File is gone from both sides, cleanup orphaned index entry
            if index_entry:
                # Remove stale index entry
                self.local_index.remove_entry(path)
                logger.debug(f"Cleaned up orphaned index entry for: {path}")
            return None  # No operation needed

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
            path: File path relative to base directory
            remote_version: Expected remote version (0 for new files)

        Returns:
            True if successful, False otherwise

        Note:
            If compression is enabled in config, files are gzip compressed before
            upload and stored with .gz extension on remote. The local index tracks
            the compressed remote path.
        """
        # Look up full path from mapping (built during scan)
        full_path = self._path_to_full_path.get(path)
        if not full_path:
            # Fallback for backward compatibility
            full_path = self._base_dir / path

        if not full_path.exists():
            logger.error(f"Cannot upload {path}: file not found")
            return False

        try:
            # Calculate MD5 using cache (of original uncompressed content)
            self.md5_cache.calculate_md5(full_path)

            # Read file content
            with open(full_path, "rb") as f:
                content = f.read()

            original_size = len(content)

            # Determine remote path and content type
            remote_path = path
            content_type = "application/octet-stream"

            # Track the effective version to use for conditional write
            effective_version = remote_version

            # Compress if enabled
            if self.config.compress:
                compressed_content = gzip.compress(content, compresslevel=6)
                # Only use compression if it actually helps
                if len(compressed_content) < original_size:
                    content = compressed_content
                    remote_path = f"{path}.gz"
                    content_type = "application/gzip"
                    # When path changes due to compression, the remote_version
                    # refers to the uncompressed file. Use 0 for new compressed file.
                    # NOTE: We intentionally do NOT delete the old uncompressed file.
                    # Both versions may coexist until explicit cleanup is requested.
                    # This preserves data integrity and avoids accidental data loss.
                    effective_version = 0
                    logger.debug(
                        f"Compressed {path}: {original_size} -> {len(content)} bytes "
                        f"({100 - len(content) * 100 // original_size}% reduction)"
                    )

            # Upload to remote
            # write_blob returns tuple (is_new, md5, version, sync_index)
            is_new, returned_md5, new_version, sync_index = self.client.write_blob(
                namespace=self.config.namespace,
                path=remote_path,
                content=content,
                expected_version=effective_version,
                content_type=content_type,
            )

            # Update local index with the entire manifest from response
            # This keeps us in sync with remote state after write
            for file_path, metadata in sync_index.files.items():
                self.local_index.update_entry(file_path, metadata)

            # Log success
            compression_note = ""
            if self.config.compress and remote_path != path:
                compression_note = (
                    f" (compressed: {original_size} -> {len(content)} bytes)"
                )

            logger.info(f"Uploaded {remote_path} (v{new_version}){compression_note}")
            return True

        except VersionConflictError as e:
            logger.warning(f"Version conflict uploading {path}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to upload {path}: {e}")
            return False

    def download_file(self, path: str) -> bool:
        """Download file from remote.

        Args:
            path: File path relative to namespace (e.g., "test.md" or "projects/alpha.md")
                  May include .gz extension for compressed files.

        Returns:
            True if successful, False otherwise

        Note:
            If the remote path ends with .gz, the content is automatically
            decompressed before writing locally. The local file will not have
            the .gz extension.
        """
        # Determine local path (strip .gz extension if present)
        local_path = path
        is_compressed = path.endswith(".gz")
        if is_compressed:
            local_path = path[:-3]  # Remove .gz extension

        # Look up full path from mapping (built during scan)
        full_path = self._path_to_full_path.get(local_path)
        if not full_path:
            # For new files being downloaded, determine where they should go
            # Check if path matches any explicit file in scan_paths
            target_dir = None
            for scan_path in self.config.scan_paths:
                scan_path = Path(scan_path)
                # Check if this scan_path is a file and matches our path
                if not scan_path.is_dir() and scan_path.name == local_path:
                    # This is the file itself (e.g., persona.md)
                    full_path = scan_path
                    break
                # Otherwise, use first directory as download location
                elif not target_dir and (scan_path.is_dir() or not scan_path.exists()):
                    target_dir = scan_path

            if not full_path and target_dir:
                full_path = target_dir / local_path
            elif not full_path:
                # Fallback to base_dir if no directory found
                full_path = self._base_dir / local_path

        try:
            # Download from remote
            # read_blob returns (content, md5, last_modified, content_type, version)
            content, md5, last_modified, content_type, version = self.client.read_blob(
                namespace=self.config.namespace, path=path
            )

            remote_size = len(content)

            # Decompress if needed (check both extension and content type)
            if is_compressed or content_type == "application/gzip":
                try:
                    content = gzip.decompress(content)
                    logger.debug(
                        f"Decompressed {path}: {remote_size} -> {len(content)} bytes"
                    )
                except gzip.BadGzipFile:
                    # Not actually gzipped, use as-is
                    logger.warning(
                        f"File {path} has .gz extension but is not gzip compressed"
                    )

            # Ensure directory exists
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file (decompressed)
            with open(full_path, "wb") as f:
                f.write(content)

            # Update MD5 cache for the downloaded file (hash of decompressed content)
            local_md5 = hashlib.md5(content).hexdigest()
            self.md5_cache.set(full_path, local_md5)

            # Create metadata object for the REMOTE file (compressed)
            # We track the remote state in the index
            file_metadata = FileMetadata(
                md5=md5,  # MD5 of compressed content on remote
                last_modified=last_modified,
                size=remote_size,  # Size on remote (compressed)
                version=version,
                is_deleted=False,
            )

            # Update local index with the remote path (including .gz)
            self.local_index.update_entry(path, file_metadata)

            # Log success
            compression_note = ""
            if is_compressed or content_type == "application/gzip":
                compression_note = (
                    f" (decompressed: {remote_size} -> {len(content)} bytes)"
                )

            logger.info(
                f"Downloaded {path} -> {local_path} (v{version}){compression_note}"
            )
            return True

        except NotFoundError:
            logger.warning(f"File not found remotely: {path}")
            return False
        except Exception as e:
            logger.error(f"Failed to download {path}: {e}")
            return False

    def delete_local(self, path: str) -> bool:
        """Delete local file.

        Args:
            path: File path relative to base directory

        Returns:
            True if successful, False otherwise
        """
        # Look up full path from mapping (built during scan)
        full_path = self._path_to_full_path.get(path)
        if not full_path:
            # Fallback for backward compatibility
            full_path = self._base_dir / path

        try:
            if full_path.exists():
                full_path.unlink()
                # Invalidate cache for deleted file
                self.md5_cache.invalidate(full_path)

            # Update local index (don't remove, mark as deleted to track remote state)
            index_entry = self.local_index.get_entry(path)
            if index_entry:
                index_entry.is_deleted = True
                self.local_index.update_entry(path, index_entry)

            # Log success

            logger.info(f"Deleted local file {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete local {path}: {e}")
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
            # delete_blob returns tuple (new_version, sync_index)
            new_version, sync_index = self.client.delete_blob(
                namespace=self.config.namespace,
                path=path,
                expected_version=remote_version,
            )

            # Update local index with the entire manifest from response
            # This keeps us in sync with remote state after delete
            for file_path, metadata in sync_index.files.items():
                self.local_index.update_entry(file_path, metadata)

            # Log success

            logger.info(f"Deleted remote file {path} (v{new_version})")
            return True

        except VersionConflictError as e:
            logger.warning(f"Version conflict deleting {path}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete remote {path}: {e}")
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
        """Scan local files based on configuration.

        Uses config.scan_paths to determine which files/directories to scan.
        Paths are relative to each scan_path to avoid duplication in S3 keys.

        For example:
        - scan_path: /personas/foo/memory/
        - file: /personas/foo/memory/notes.md
        - stored path: notes.md (not memory/notes.md)

        Returns:
            Dictionary mapping paths to FileInfo
        """
        files = {}
        # Clear and rebuild path mapping
        self._path_to_full_path.clear()

        # Scan configured paths
        for scan_path in self.config.scan_paths:
            scan_path = Path(scan_path)

            if not scan_path.exists():
                logger.debug(f"Scan path does not exist: {scan_path}")
                continue

            if scan_path.is_file():
                # Single file (e.g., persona.md)
                # Use just the filename as the path
                rel_path = scan_path.name

                try:
                    # Use cache for MD5 calculation
                    md5 = self.md5_cache.calculate_md5(scan_path)

                    files[rel_path] = FileInfo(
                        path=rel_path,
                        md5=md5,
                        size=scan_path.stat().st_size,
                        last_modified=datetime.fromtimestamp(
                            scan_path.stat().st_mtime, tz=timezone.utc
                        ),
                    )
                    # Store mapping for file operations
                    self._path_to_full_path[rel_path] = scan_path

                except Exception as e:
                    logger.warning(f"Failed to read {scan_path}: {e}")

            elif scan_path.is_dir():
                # Directory - scan recursively
                for file_path in scan_path.rglob("*"):
                    if not file_path.is_file():
                        continue

                    # Skip sync metadata files
                    if file_path.name in [
                        ".sync-index.json",
                        ".sync-index-memory.json",
                        ".sync-index-history.json",
                        ".sync-log.jsonl",
                        ".sync-log-memory.jsonl",
                        ".sync-log-history.jsonl",
                    ]:
                        continue

                    # Get path relative to scan_path (not base_dir!)
                    # This ensures paths don't duplicate directory structure
                    try:
                        rel_path = file_path.relative_to(scan_path)
                    except ValueError:
                        # Fallback: just use filename
                        rel_path = Path(file_path.name)

                    # Calculate MD5 using cache
                    try:
                        md5 = self.md5_cache.calculate_md5(file_path)

                        files[str(rel_path)] = FileInfo(
                            path=str(rel_path),
                            md5=md5,
                            size=file_path.stat().st_size,
                            last_modified=datetime.fromtimestamp(
                                file_path.stat().st_mtime, tz=timezone.utc
                            ),
                        )
                        # Store mapping for file operations
                        self._path_to_full_path[str(rel_path)] = file_path

                    except Exception as e:
                        logger.warning(f"Failed to read {rel_path}: {e}")
                        continue

        return files

    def _calculate_md5(self, content: bytes) -> str:
        """Calculate MD5 hash of content.

        Args:
            content: File content

        Returns:
            MD5 hash as hex string
        """
        return hashlib.md5(content).hexdigest()
