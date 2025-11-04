"""Tests for memory sync module."""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from silica.developer.memory.sync import (
    LocalIndex,
    SyncOperationLog,
)
from silica.developer.memory.proxy_client import FileMetadata


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
