"""Tests for memory sync module."""

import json

import pytest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from silica.developer.memory.sync import (
    LocalIndex,
    SyncOperationLog,
    SyncEngine,
    SyncPlan,
    SyncOperationDetail,
    SyncResult,
    SyncStatus,
)
from silica.developer.memory.proxy_client import (
    FileMetadata,
    MemoryProxyClient,
    SyncIndexResponse,
)
from unittest.mock import AsyncMock


def make_sync_index_response(files_list):
    """Helper to create SyncIndexResponse from list of file dicts."""
    files_dict = {}
    for file_dict in files_list:
        path = file_dict["path"]
        files_dict[path] = FileMetadata(
            md5=file_dict["md5"],
            last_modified=datetime.fromisoformat(file_dict["last_modified"]),
            size=file_dict["size"],
            version=file_dict["version"],
            is_deleted=file_dict.get("is_deleted", False),
        )

    return SyncIndexResponse(
        files=files_dict,
        index_last_modified=datetime.now(timezone.utc),
        index_version=max((f.version for f in files_dict.values()), default=0),
    )


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def local_index(temp_dir):
    """Create a LocalIndex instance."""
    return LocalIndex(temp_dir)


@pytest.fixture
def operation_log(temp_dir):
    """Create a SyncOperationLog instance."""
    return SyncOperationLog(temp_dir)


class TestLocalIndex:
    """Tests for LocalIndex class."""

    def test_init(self, local_index, temp_dir):
        """Test initialization."""
        assert local_index.base_dir == temp_dir
        assert local_index.index_file == temp_dir / ".sync-index.json"
        assert not local_index._loaded

    def test_load_empty(self, local_index):
        """Test loading when no index file exists."""
        entries = local_index.load()

        assert entries == {}
        assert local_index._loaded

    def test_save_and_load(self, local_index):
        """Test saving and loading index."""
        # Create some entries
        metadata1 = FileMetadata(
            md5="abc123",
            last_modified=datetime.now(timezone.utc),
            size=100,
            version=1000,
            is_deleted=False,
        )
        metadata2 = FileMetadata(
            md5="def456",
            last_modified=datetime.now(timezone.utc),
            size=200,
            version=2000,
            is_deleted=False,
        )

        local_index.update_entry("file1.md", metadata1)
        local_index.update_entry("file2.md", metadata2)
        local_index.save()

        # Create new index and load
        local_index2 = LocalIndex(local_index.base_dir)
        entries = local_index2.load()

        assert len(entries) == 2
        assert "file1.md" in entries
        assert "file2.md" in entries
        assert entries["file1.md"].md5 == "abc123"
        assert entries["file2.md"].md5 == "def456"

    def test_update_entry(self, local_index):
        """Test updating an entry."""
        metadata = FileMetadata(
            md5="test123",
            last_modified=datetime.now(timezone.utc),
            size=50,
            version=500,
            is_deleted=False,
        )

        local_index.update_entry("test.md", metadata)

        assert "test.md" in local_index.get_all_entries()
        assert local_index.get_entry("test.md").md5 == "test123"

    def test_remove_entry(self, local_index):
        """Test removing an entry."""
        metadata = FileMetadata(
            md5="test123",
            last_modified=datetime.now(timezone.utc),
            size=50,
            version=500,
            is_deleted=False,
        )

        local_index.update_entry("test.md", metadata)
        assert local_index.get_entry("test.md") is not None

        local_index.remove_entry("test.md")
        assert local_index.get_entry("test.md") is None

    def test_get_entry_not_found(self, local_index):
        """Test getting non-existent entry."""
        assert local_index.get_entry("missing.md") is None

    def test_get_all_entries(self, local_index):
        """Test getting all entries."""
        metadata1 = FileMetadata(
            md5="abc",
            last_modified=datetime.now(timezone.utc),
            size=10,
            version=100,
            is_deleted=False,
        )
        metadata2 = FileMetadata(
            md5="def",
            last_modified=datetime.now(timezone.utc),
            size=20,
            version=200,
            is_deleted=False,
        )

        local_index.update_entry("file1.md", metadata1)
        local_index.update_entry("file2.md", metadata2)

        entries = local_index.get_all_entries()
        assert len(entries) == 2
        assert "file1.md" in entries
        assert "file2.md" in entries

    def test_clear(self, local_index):
        """Test clearing the index."""
        metadata = FileMetadata(
            md5="test",
            last_modified=datetime.now(timezone.utc),
            size=10,
            version=100,
            is_deleted=False,
        )

        local_index.update_entry("test.md", metadata)
        assert len(local_index.get_all_entries()) == 1

        local_index.clear()
        assert len(local_index.get_all_entries()) == 0

    def test_persistence(self, local_index):
        """Test that index persists across instances."""
        metadata = FileMetadata(
            md5="persist",
            last_modified=datetime.now(timezone.utc),
            size=100,
            version=1000,
            is_deleted=False,
        )

        local_index.update_entry("persistent.md", metadata)
        local_index.save()

        # Create new instance
        new_index = LocalIndex(local_index.base_dir)
        new_index.load()

        entry = new_index.get_entry("persistent.md")
        assert entry is not None
        assert entry.md5 == "persist"
        assert entry.version == 1000


class TestSyncOperationLog:
    """Tests for SyncOperationLog class."""

    def test_init(self, operation_log, temp_dir):
        """Test initialization."""
        assert operation_log.base_dir == temp_dir
        assert operation_log.log_file == temp_dir / ".sync-log.jsonl"

    def test_log_operation(self, operation_log):
        """Test logging an operation."""
        op_id = operation_log.log_operation(
            op_type="upload",
            path="test.md",
            status="success",
        )

        assert op_id is not None
        assert isinstance(op_id, str)
        assert operation_log.log_file.exists()

    def test_log_operation_with_error(self, operation_log):
        """Test logging a failed operation."""
        op_id = operation_log.log_operation(
            op_type="download",
            path="failed.md",
            status="failed",
            error="Network timeout",
        )

        assert op_id is not None

        # Verify it appears in failed operations
        failed = operation_log.get_failed_operations()
        assert len(failed) == 1
        assert failed[0].path == "failed.md"
        assert failed[0].error == "Network timeout"

    def test_log_operation_with_metadata(self, operation_log):
        """Test logging with additional metadata."""
        operation_log.log_operation(
            op_type="upload",
            path="test.md",
            status="success",
            metadata={"size": 1024, "md5": "abc123"},
        )

        operations = operation_log.get_operations_for_path("test.md")
        assert len(operations) == 1
        assert operations[0].metadata["size"] == 1024
        assert operations[0].metadata["md5"] == "abc123"

    def test_get_failed_operations(self, operation_log):
        """Test getting failed operations."""
        # Log some operations
        operation_log.log_operation("upload", "file1.md", "success")
        operation_log.log_operation("download", "file2.md", "failed", error="Error 1")
        operation_log.log_operation("upload", "file3.md", "failed", error="Error 2")
        operation_log.log_operation("delete", "file4.md", "success")

        failed = operation_log.get_failed_operations()

        assert len(failed) == 2
        assert all(op.status == "failed" for op in failed)
        assert {op.path for op in failed} == {"file2.md", "file3.md"}

    def test_get_recent_operations(self, operation_log):
        """Test getting recent operations."""
        # Log several operations
        for i in range(10):
            operation_log.log_operation(
                "upload",
                f"file{i}.md",
                "success",
            )

        recent = operation_log.get_recent_operations(limit=5)

        assert len(recent) == 5
        # Should be in reverse order (newest first)
        assert recent[0].path == "file9.md"
        assert recent[4].path == "file5.md"

    def test_get_operations_for_path(self, operation_log):
        """Test getting operations for specific path."""
        # Log operations for different paths
        operation_log.log_operation("upload", "test.md", "success")
        operation_log.log_operation("download", "test.md", "success")
        operation_log.log_operation("upload", "other.md", "success")
        operation_log.log_operation("delete", "test.md", "success")

        ops = operation_log.get_operations_for_path("test.md")

        assert len(ops) == 3
        assert all(op.path == "test.md" for op in ops)

    def test_get_statistics(self, operation_log):
        """Test getting operation statistics."""
        # Log various operations
        operation_log.log_operation("upload", "file1.md", "success")
        operation_log.log_operation("upload", "file2.md", "success")
        operation_log.log_operation("download", "file3.md", "success")
        operation_log.log_operation("upload", "file4.md", "failed", error="Error")
        operation_log.log_operation("delete", "file5.md", "success")

        stats = operation_log.get_statistics()

        assert stats["total_operations"] == 5
        assert stats["by_type"]["upload"] == 3
        assert stats["by_type"]["download"] == 1
        assert stats["by_type"]["delete"] == 1
        assert stats["by_status"]["success"] == 4
        assert stats["by_status"]["failed"] == 1

    def test_persistence(self, operation_log):
        """Test that log persists across instances."""
        # Log some operations
        operation_log.log_operation("upload", "test1.md", "success")
        operation_log.log_operation("download", "test2.md", "success")

        # Create new instance
        new_log = SyncOperationLog(operation_log.base_dir)
        recent = new_log.get_recent_operations(limit=10)

        assert len(recent) == 2
        paths = {op.path for op in recent}
        assert paths == {"test1.md", "test2.md"}

    def test_empty_log(self, operation_log):
        """Test operations on empty log."""
        assert operation_log.get_failed_operations() == []
        assert operation_log.get_recent_operations() == []
        assert operation_log.get_operations_for_path("any.md") == []

        stats = operation_log.get_statistics()
        assert stats["total_operations"] == 0

    def test_truncate_after_sync(self, operation_log):
        """Test truncating log after sync."""
        from datetime import timedelta, datetime, timezone

        # Create some old successful operations (> 7 days)
        old_time = datetime.now(timezone.utc) - timedelta(days=10)

        # Log some operations
        operation_log.log_operation("upload", "old_success.md", "success")
        operation_log.log_operation("upload", "recent_success.md", "success")
        operation_log.log_operation("download", "failed.md", "failed", error="Error")

        # Manually modify timestamps to simulate old operations
        operations = operation_log._read_all_operations()
        operations[0].timestamp = old_time  # Make first operation old

        # Rewrite with modified timestamps
        with open(operation_log.log_file, "w") as f:
            for op in operations:
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

        # Truncate
        removed = operation_log.truncate_after_sync(keep_days=7)

        # Should remove 1 old successful operation
        assert removed == 1

        # Check remaining operations
        remaining = operation_log._read_all_operations()
        paths = {op.path for op in remaining}

        # Should keep recent success and failed operation
        assert "recent_success.md" in paths
        assert "failed.md" in paths
        assert "old_success.md" not in paths

    def test_truncate_keeps_all_failed(self, operation_log):
        """Test that truncation keeps all failed operations regardless of age."""
        from datetime import timedelta, datetime, timezone

        old_time = datetime.now(timezone.utc) - timedelta(days=30)

        # Log an old failed operation
        operation_log.log_operation(
            "upload", "old_failed.md", "failed", error="Old error"
        )

        # Manually modify timestamp
        operations = operation_log._read_all_operations()
        operations[0].timestamp = old_time

        with open(operation_log.log_file, "w") as f:
            for op in operations:
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

        # Truncate
        removed = operation_log.truncate_after_sync(keep_days=7)

        # Should not remove failed operation
        assert removed == 0

        remaining = operation_log._read_all_operations()
        assert len(remaining) == 1
        assert remaining[0].path == "old_failed.md"


class TestSyncEngine:
    """Tests for SyncEngine class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock MemoryProxyClient."""
        client = AsyncMock(spec=MemoryProxyClient)
        return client

    @pytest.fixture
    def sync_engine(self, temp_dir, mock_client):
        """Create a SyncEngine instance."""
        return SyncEngine(
            client=mock_client,
            local_base_dir=temp_dir,
            namespace="test-persona",
        )

    def test_init(self, sync_engine, temp_dir, mock_client):
        """Test initialization."""
        assert sync_engine.client == mock_client
        assert sync_engine.local_base_dir == temp_dir
        assert sync_engine.namespace == "test-persona"
        assert isinstance(sync_engine.local_index, LocalIndex)
        assert isinstance(sync_engine.operation_log, SyncOperationLog)

    def test_analyze_empty_sync(self, sync_engine, mock_client):
        """Test analyzing sync when everything is empty."""
        # Configure mock
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        plan = sync_engine.analyze_sync_operations()

        assert plan.total_operations == 0
        assert len(plan.upload) == 0
        assert len(plan.download) == 0
        assert len(plan.conflicts) == 0

    def test_analyze_new_local_file(self, sync_engine, mock_client, temp_dir):
        """Test analyzing sync with a new local file."""
        # Create a local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        test_file.write_text("test content")

        # Configure AsyncMock
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        plan = sync_engine.analyze_sync_operations()

        assert plan.total_operations == 1
        assert len(plan.upload) == 1
        assert plan.upload[0].path == "memory/test.md"
        assert plan.upload[0].reason == "New local file"

    def test_analyze_new_remote_file(self, sync_engine, mock_client):
        """Test analyzing sync with a new remote file."""
        # Configure AsyncMock
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/remote.md",
                    "md5": "abc123",
                    "size": 100,
                    "version": 1000,
                    "last_modified": "2025-01-01T00:00:00Z",
                    "is_deleted": False,
                }
            ]
        )

        plan = sync_engine.analyze_sync_operations()

        assert plan.total_operations == 1
        assert len(plan.download) == 1
        assert plan.download[0].path == "memory/remote.md"
        assert plan.download[0].reason == "New remote file"

    def test_analyze_files_in_sync(self, sync_engine, mock_client, temp_dir):
        """Test analyzing when files are in sync."""
        # Create a local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        content = b"test content"
        test_file.write_bytes(content)

        # Calculate MD5
        import hashlib

        md5 = hashlib.md5(content).hexdigest()

        # Configure AsyncMock
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/test.md",
                    "md5": md5,
                    "size": len(content),
                    "version": 1000,
                    "last_modified": "2025-01-01T00:00:00Z",
                    "is_deleted": False,
                }
            ]
        )

        plan = sync_engine.analyze_sync_operations()

        # Files are in sync - no operations needed
        assert plan.total_operations == 0

    def test_analyze_local_modified(self, sync_engine, mock_client, temp_dir):
        """Test analyzing when local file is modified."""
        # Create a local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        content = b"new content"
        test_file.write_bytes(content)

        # Calculate MD5
        import hashlib

        hashlib.md5(content).hexdigest()

        # Setup local index with old version
        sync_engine.local_index.load()
        old_metadata = FileMetadata(
            md5="old_md5",
            last_modified=datetime.now(timezone.utc),
            size=50,
            version=1000,
            is_deleted=False,
        )
        sync_engine.local_index.update_entry("memory/test.md", old_metadata)
        sync_engine.local_index.save()  # Save so it persists across load() calls

        # Configure mock
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/test.md",
                    "md5": "old_md5",
                    "size": 50,
                    "version": 1000,
                    "last_modified": "2025-01-01T00:00:00Z",
                    "is_deleted": False,
                }
            ]
        )

        plan = sync_engine.analyze_sync_operations()

        assert plan.total_operations == 1
        assert len(plan.upload) == 1
        assert plan.upload[0].path == "memory/test.md"
        assert plan.upload[0].reason == "Local file modified"

    def test_analyze_remote_modified(self, sync_engine, mock_client, temp_dir):
        """Test analyzing when remote file is modified."""
        # Create a local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        content = b"old content"
        test_file.write_bytes(content)

        # Calculate MD5
        import hashlib

        md5 = hashlib.md5(content).hexdigest()

        # Setup local index with same version as local
        sync_engine.local_index.load()
        old_metadata = FileMetadata(
            md5=md5,
            last_modified=datetime.now(timezone.utc),
            size=len(content),
            version=1000,
            is_deleted=False,
        )
        sync_engine.local_index.update_entry("memory/test.md", old_metadata)
        sync_engine.local_index.save()  # Save so it persists across load() calls

        # Configure mock
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/test.md",
                    "md5": "new_remote_md5",
                    "size": 100,
                    "version": 1001,
                    "last_modified": "2025-01-02T00:00:00Z",
                    "is_deleted": False,
                }
            ]
        )

        plan = sync_engine.analyze_sync_operations()

        assert plan.total_operations == 1
        assert len(plan.download) == 1
        assert plan.download[0].path == "memory/test.md"
        assert plan.download[0].reason == "Remote file modified"

    def test_analyze_both_modified_conflict(self, sync_engine, mock_client, temp_dir):
        """Test analyzing when both local and remote are modified."""
        # Create a local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        content = b"new local content"
        test_file.write_bytes(content)

        # Calculate MD5
        import hashlib

        hashlib.md5(content).hexdigest()

        # Setup local index with old version
        sync_engine.local_index.load()
        old_metadata = FileMetadata(
            md5="old_md5",
            last_modified=datetime.now(timezone.utc),
            size=50,
            version=1000,
            is_deleted=False,
        )
        sync_engine.local_index.update_entry("memory/test.md", old_metadata)
        sync_engine.local_index.save()  # Save so it persists across load() calls

        # Configure mock
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/test.md",
                    "md5": "new_remote_md5",
                    "size": 100,
                    "version": 1001,
                    "last_modified": "2025-01-02T00:00:00Z",
                    "is_deleted": False,
                }
            ]
        )

        plan = sync_engine.analyze_sync_operations()

        assert plan.has_conflicts
        assert len(plan.conflicts) == 1
        assert plan.conflicts[0].path == "memory/test.md"
        assert (
            plan.conflicts[0].reason == "Both local and remote modified since last sync"
        )

    def test_upload_file(self, sync_engine, mock_client, temp_dir):
        """Test uploading a file."""
        # Create a local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        content = b"test content"
        test_file.write_bytes(content)

        # Configure AsyncMock
        mock_client.write_blob.return_value = (True, "mock_md5", 1001)

        result = sync_engine.upload_file("memory/test.md", 1000)

        assert result is True
        mock_client.write_blob.assert_called_once()

        # Check local index was updated
        index_entry = sync_engine.local_index.get_entry("memory/test.md")
        assert index_entry is not None
        assert index_entry.version == 1001

    def test_upload_file_not_found(self, sync_engine, mock_client):
        """Test uploading a file that doesn't exist."""
        result = sync_engine.upload_file("nonexistent.md", 0)

        assert result is False
        mock_client.write_blob.assert_not_called()

    def test_download_file(self, sync_engine, mock_client, temp_dir):
        """Test downloading a file."""
        content = b"downloaded content"
        md5 = "abc123"
        last_modified = datetime.now(timezone.utc)
        content_type = "text/markdown"
        version = 1000

        # Configure AsyncMock
        # read_blob returns (content, md5, last_modified, content_type, version)
        mock_client.read_blob.return_value = (
            content,
            md5,
            last_modified,
            content_type,
            version,
        )

        result = sync_engine.download_file("memory/test.md")

        assert result is True
        mock_client.read_blob.assert_called_once()

        # Check file was created
        test_file = temp_dir / "memory" / "test.md"
        assert test_file.exists()
        assert test_file.read_bytes() == content

        # Check local index was updated
        index_entry = sync_engine.local_index.get_entry("memory/test.md")
        assert index_entry is not None
        assert index_entry.version == 1000

    def test_delete_local(self, sync_engine, temp_dir):
        """Test deleting a local file."""
        # Create a local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        test_file.write_text("test")

        # Add to index
        metadata = FileMetadata(
            md5="abc",
            last_modified=datetime.now(timezone.utc),
            size=4,
            version=1000,
            is_deleted=False,
        )
        sync_engine.local_index.update_entry("memory/test.md", metadata)

        result = sync_engine.delete_local("memory/test.md")

        assert result is True
        assert not test_file.exists()

        # Check index entry is marked as deleted
        index_entry = sync_engine.local_index.get_entry("memory/test.md")
        assert index_entry is not None
        assert index_entry.is_deleted is True

    def test_delete_remote(self, sync_engine, mock_client):
        """Test deleting a remote file."""
        # Configure AsyncMock
        mock_client.delete_blob.return_value = 1001

        result = sync_engine.delete_remote("memory/test.md", 1000)

        assert result is True
        mock_client.delete_blob.assert_called_once_with(
            namespace="test-persona",
            path="memory/test.md",
            expected_version=1000,
        )

        # Check local index was updated with tombstone
        index_entry = sync_engine.local_index.get_entry("memory/test.md")
        assert index_entry is not None
        assert index_entry.is_deleted is True
        assert index_entry.version == 1001

    def test_execute_sync_empty_plan(self, sync_engine):
        """Test executing an empty sync plan."""
        plan = SyncPlan()

        result = sync_engine.execute_sync(plan, show_progress=False)

        assert result.total == 0
        assert result.success_rate == 100.0

    def test_execute_sync_with_uploads(self, sync_engine, mock_client, temp_dir):
        """Test executing a sync plan with uploads."""
        # Create a local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        test_file = memory_dir / "test.md"
        test_file.write_text("test content")

        # Configure AsyncMock
        mock_client.write_blob.return_value = (True, "mock_md5", 1001)

        # Create plan
        plan = SyncPlan(
            upload=[
                SyncOperationDetail(
                    type="upload",
                    path="memory/test.md",
                    reason="New file",
                    remote_version=0,
                )
            ]
        )

        result = sync_engine.execute_sync(plan, show_progress=False)

        assert result.total == 1
        assert len(result.succeeded) == 1
        assert len(result.failed) == 0

    def test_scan_local_files(self, sync_engine, temp_dir):
        """Test scanning local files."""
        # Create some files
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        (memory_dir / "test1.md").write_text("content1")
        (memory_dir / "test2.md").write_text("content2")

        history_dir = temp_dir / "history"
        history_dir.mkdir()
        (history_dir / "session.json").write_text("{}")

        # Create persona.md
        (temp_dir / "persona.md").write_text("persona content")

        files = sync_engine._scan_local_files()

        # Should find all files except sync metadata
        assert "memory/test1.md" in files
        assert "memory/test2.md" in files
        assert "history/session.json" in files
        assert "persona.md" in files

        # Should not include sync metadata files
        assert ".sync-index.json" not in files
        assert ".sync-log.jsonl" not in files

    def test_calculate_md5(self, sync_engine):
        """Test MD5 calculation."""
        content = b"test content"
        md5 = sync_engine._calculate_md5(content)

        assert isinstance(md5, str)
        assert len(md5) == 32  # MD5 is 32 hex chars


class TestDataModels:
    """Tests for data model classes."""

    def test_sync_plan_total_operations(self):
        """Test SyncPlan.total_operations property."""
        plan = SyncPlan(
            upload=[SyncOperationDetail("upload", "file1.md", "reason")],
            download=[
                SyncOperationDetail("download", "file2.md", "reason"),
                SyncOperationDetail("download", "file3.md", "reason"),
            ],
            delete_local=[SyncOperationDetail("delete_local", "file4.md", "reason")],
        )

        assert plan.total_operations == 4

    def test_sync_plan_has_conflicts(self):
        """Test SyncPlan.has_conflicts property."""
        plan1 = SyncPlan()
        assert not plan1.has_conflicts

        plan2 = SyncPlan(
            conflicts=[SyncOperationDetail("conflict", "file.md", "Both modified")]
        )
        assert plan2.has_conflicts

    def test_sync_result_total(self):
        """Test SyncResult.total property."""
        result = SyncResult(
            succeeded=[SyncOperationDetail("upload", "file1.md", "reason")],
            failed=[SyncOperationDetail("download", "file2.md", "reason")],
            conflicts=[SyncOperationDetail("conflict", "file3.md", "reason")],
            skipped=[SyncOperationDetail("upload", "file4.md", "reason")],
        )

        assert result.total == 4

    def test_sync_result_success_rate(self):
        """Test SyncResult.success_rate property."""
        result1 = SyncResult(
            succeeded=[
                SyncOperationDetail("upload", "file1.md", "reason"),
                SyncOperationDetail("upload", "file2.md", "reason"),
            ],
            failed=[SyncOperationDetail("download", "file3.md", "reason")],
        )

        assert result1.success_rate == pytest.approx(66.67, rel=0.1)

        # Empty result should be 100%
        result2 = SyncResult()
        assert result2.success_rate == 100.0

    def test_sync_status_needs_sync(self):
        """Test SyncStatus.needs_sync property."""
        status1 = SyncStatus()
        assert not status1.needs_sync

        status2 = SyncStatus(pending_upload=[{"path": "file.md"}])
        assert status2.needs_sync

        status3 = SyncStatus(conflicts=[{"path": "file.md"}])
        assert status3.needs_sync


"""Tests for memory sync module."""
