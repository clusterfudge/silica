"""History sync engine with compression support.

This module provides history-specific sync functionality with:
- Client authority (client pushes, remote archives)
- Compression (gzip) for all history files in transit and at rest
- Session-specific namespaces
- Push-mostly semantics (pull only for resume/browse)
"""

import gzip
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from silica.developer.memory.proxy_client import (
    FileMetadata,
    MemoryProxyClient,
    VersionConflictError,
    NotFoundError,
)

if TYPE_CHECKING:
    from silica.developer.memory.sync_config import SyncConfig

logger = logging.getLogger(__name__)


@dataclass
class HistoryPushResult:
    """Result of a history push operation."""

    succeeded: list[str]  # List of file paths successfully pushed
    failed: list[tuple[str, Exception]]  # List of (path, error) tuples
    compressed_sizes: dict[str, tuple[int, int]]  # path -> (original, compressed) bytes
    duration: float = 0.0

    @property
    def total(self) -> int:
        """Get total number of files attempted."""
        return len(self.succeeded) + len(self.failed)

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total == 0:
            return 100.0
        return (len(self.succeeded) / self.total) * 100.0

    def compression_ratio(self, path: str) -> float:
        """Get compression ratio for a file (0.0 to 1.0, lower is better)."""
        if path not in self.compressed_sizes:
            return 1.0
        original, compressed = self.compressed_sizes[path]
        if original == 0:
            return 1.0
        return compressed / original


class HistoryLocalIndex:
    """Track local history sync state.

    Simpler than memory index since history is push-mostly:
    - Track what we've pushed
    - Track versions for resumption
    - No need to track remote authority
    """

    def __init__(self, index_file: Path):
        """Initialize history index.

        Args:
            index_file: Path to the index file (e.g., .../history/session-1/.sync-index.json)
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
            logger.debug(f"No history index found at {self.index_file}")
            self._index = {}
            self._loaded = True
            return self._index

        try:
            with open(self.index_file, "r") as f:
                data = json.load(f)

            # Convert dict to FileMetadata objects
            self._index = {}
            for path, metadata_dict in data.get("files", {}).items():
                metadata_dict["last_modified"] = datetime.fromisoformat(
                    metadata_dict["last_modified"]
                )
                self._index[path] = FileMetadata(**metadata_dict)

            self._loaded = True
            logger.debug(f"Loaded history index with {len(self._index)} entries")
            return self._index

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to load history index: {e}")
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
            logger.debug(f"Saved history index with {len(self._index)} entries")
        except OSError as e:
            logger.error(f"Failed to save history index: {e}")
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
        logger.debug(f"Updated history index entry: {path} (v{metadata.version})")

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


class HistorySyncEngine:
    """Sync engine for session history with compression.

    History sync differs from memory sync:
    - Client is authoritative (we push, remote archives)
    - All files are compressed with gzip in transit and at rest
    - Push-mostly: only pull for resume/browse scenarios
    - Session-specific: each session has independent sync
    """

    def __init__(
        self,
        client: MemoryProxyClient,
        config: "SyncConfig",
        compression_level: int = 6,
    ):
        """Initialize history sync engine.

        Args:
            client: Memory proxy client
            config: Sync configuration for this session
            compression_level: gzip compression level (0-9, default 6)
        """
        self.client = client
        self.config = config
        self.compression_level = compression_level

        self.local_index = HistoryLocalIndex(config.index_file)

        # Derive session directory from config
        self._session_dir = self._determine_session_dir()

    def _determine_session_dir(self) -> Path:
        """Determine session directory from config.

        Returns:
            Path to the session directory
        """
        if not self.config.scan_paths:
            # Fallback: use index file's parent
            return self.config.index_file.parent

        # Use first scan path (should be the session directory)
        return Path(self.config.scan_paths[0])

    def push_all(self, show_progress: bool = True) -> HistoryPushResult:
        """Push all local history files to remote with compression.

        This is the main operation for history sync. It:
        1. Scans local files in the session directory
        2. Determines which files need pushing (new or modified)
        3. Compresses each file with gzip
        4. Uploads compressed files to remote
        5. Updates local index

        Args:
            show_progress: Whether to show progress bar

        Returns:
            HistoryPushResult with operation results
        """
        import time

        start_time = time.time()
        result = HistoryPushResult(
            succeeded=[],
            failed=[],
            compressed_sizes={},
        )

        # Load index
        self.local_index.load()

        # Scan local files
        local_files = self._scan_local_files()

        if not local_files:
            logger.debug("No history files to push")
            result.duration = time.time() - start_time
            return result

        # Set up progress bar if requested
        progress_bar = None
        task_id = None
        total_files = len(local_files)

        if show_progress and total_files > 0:
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
                    "[cyan]Pushing history files...", total=total_files
                )
            except ImportError:
                # rich not available, continue without progress
                pass

        try:
            # Push each file
            for file_path, file_info in local_files.items():
                # Check if we need to push this file
                index_entry = self.local_index.get_entry(file_path)

                if index_entry and index_entry.md5 == file_info["md5"]:
                    # Already pushed, skip
                    logger.debug(f"Skipping {file_path} (already pushed)")
                    result.succeeded.append(file_path)
                    if progress_bar and task_id is not None:
                        progress_bar.update(task_id, advance=1)
                    continue

                # Push the file
                try:
                    compressed_size = self._push_file(
                        file_path, file_info, index_entry
                    )
                    result.succeeded.append(file_path)
                    result.compressed_sizes[file_path] = (
                        file_info["size"],
                        compressed_size,
                    )
                    logger.info(
                        f"Pushed {file_path}: {file_info['size']} → {compressed_size} bytes "
                        f"({compressed_size / file_info['size'] * 100:.1f}%)"
                    )
                except Exception as e:
                    logger.error(f"Failed to push {file_path}: {e}")
                    result.failed.append((file_path, e))
                finally:
                    if progress_bar and task_id is not None:
                        progress_bar.update(task_id, advance=1)

            # Save updated index
            self.local_index.save()

            result.duration = time.time() - start_time
            return result

        finally:
            # Clean up progress bar
            if progress_bar:
                progress_bar.stop()

    def _push_file(
        self,
        file_path: str,
        file_info: dict,
        index_entry: FileMetadata | None,
    ) -> int:
        """Push a single file with compression.

        Args:
            file_path: Relative file path
            file_info: File information (md5, size, content)
            index_entry: Existing index entry (for version)

        Returns:
            Compressed file size in bytes

        Raises:
            Exception: If push fails
        """
        # Read file content
        full_path = self._session_dir / file_path
        with open(full_path, "rb") as f:
            content = f.read()

        # Compress with gzip
        compressed = gzip.compress(content, compresslevel=self.compression_level)

        # Determine expected version
        expected_version = index_entry.version if index_entry else 0

        # Upload compressed file (with .gz extension)
        remote_path = f"{file_path}.gz"
        is_new, returned_md5, new_version = self.client.write_blob(
            namespace=self.config.namespace,
            path=remote_path,
            content=compressed,
            expected_version=expected_version,
            content_type="application/gzip",
        )

        # Update local index with original MD5
        self.local_index.update_entry(
            file_path,
            FileMetadata(
                md5=file_info["md5"],
                last_modified=datetime.now(timezone.utc),
                size=file_info["size"],
                version=new_version,
                is_deleted=False,
            ),
        )

        return len(compressed)

    def pull_session(self, show_progress: bool = True) -> dict[str, Path]:
        """Pull all session files from remote (for resume/browse).

        Downloads and decompresses all .gz files for this session.

        Args:
            show_progress: Whether to show progress bar

        Returns:
            Dictionary mapping remote paths to local file paths

        Raises:
            Exception: If pull fails
        """
        # Get remote index
        remote_index_response = self.client.get_sync_index(self.config.namespace)
        remote_files = remote_index_response.files

        if not remote_files:
            logger.debug(f"No remote files to pull for {self.config.namespace}")
            return {}

        # Filter out deleted files
        files_to_pull = {
            path: metadata
            for path, metadata in remote_files.items()
            if not metadata.is_deleted
        }

        if not files_to_pull:
            logger.debug("No non-deleted files to pull")
            return {}

        # Set up progress bar
        progress_bar = None
        task_id = None
        total_files = len(files_to_pull)

        if show_progress and total_files > 0:
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
                    "[cyan]Pulling history files...", total=total_files
                )
            except ImportError:
                pass

        try:
            pulled_files = {}

            for remote_path, metadata in files_to_pull.items():
                try:
                    local_path = self._pull_file(remote_path)
                    pulled_files[remote_path] = local_path
                    logger.info(f"Pulled {remote_path} -> {local_path}")
                except Exception as e:
                    logger.error(f"Failed to pull {remote_path}: {e}")
                    # Continue with other files
                finally:
                    if progress_bar and task_id is not None:
                        progress_bar.update(task_id, advance=1)

            # Save index
            self.local_index.save()

            return pulled_files

        finally:
            if progress_bar:
                progress_bar.stop()

    def _pull_file(self, remote_path: str) -> Path:
        """Pull and decompress a single file.

        Args:
            remote_path: Remote file path (may include .gz extension)

        Returns:
            Local file path

        Raises:
            Exception: If pull fails
        """
        # Read from remote
        content, md5, last_modified, content_type, version = self.client.read_blob(
            namespace=self.config.namespace,
            path=remote_path,
        )

        # Decompress if needed
        if remote_path.endswith(".gz"):
            content = gzip.decompress(content)
            local_filename = remote_path.removesuffix(".gz")
        else:
            local_filename = remote_path

        # Write locally
        local_path = self._session_dir / local_filename
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(content)

        # Calculate MD5 of decompressed content
        local_md5 = hashlib.md5(content).hexdigest()

        # Update index
        self.local_index.update_entry(
            local_filename,
            FileMetadata(
                md5=local_md5,
                last_modified=last_modified,
                size=len(content),
                version=version,
                is_deleted=False,
            ),
        )

        return local_path

    def _scan_local_files(self) -> dict[str, dict]:
        """Scan local session directory for files to push.

        Returns:
            Dictionary mapping relative paths to file info (md5, size, mtime)
        """
        files = {}

        if not self._session_dir.exists():
            return files

        for file_path in self._session_dir.rglob("*"):
            if not file_path.is_file():
                continue

            # Skip sync metadata files
            if file_path.name in [
                ".sync-index.json",
                ".sync-index-history.json",
                ".sync-log.jsonl",
            ]:
                continue

            # Get relative path
            try:
                rel_path = file_path.relative_to(self._session_dir)
            except ValueError:
                continue

            # Read file and calculate MD5
            try:
                with open(file_path, "rb") as f:
                    content = f.read()

                files[str(rel_path)] = {
                    "md5": hashlib.md5(content).hexdigest(),
                    "size": len(content),
                    "mtime": file_path.stat().st_mtime,
                }
            except Exception as e:
                logger.warning(f"Failed to read {rel_path}: {e}")
                continue

        return files
