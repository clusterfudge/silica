"""Tests for memory sync module."""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from silica.developer.memory.sync import (
    LocalIndex,
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
    return LocalIndex(temp_dir / ".sync-index.json")


class TestLocalIndex:
    """Tests for LocalIndex class."""

    def test_init(self, local_index, temp_dir):
        """Test initialization."""
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
        local_index2 = LocalIndex(local_index.index_file)
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
        new_index = LocalIndex(local_index.index_file)
        new_index.load()

        entry = new_index.get_entry("persistent.md")
        assert entry is not None
        assert entry.md5 == "persist"
        assert entry.version == 1000


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
        from silica.developer.memory.sync_config import SyncConfig

        # Create a test config
        config = SyncConfig(
            namespace="test-persona",
            scan_paths=[temp_dir / "memory", temp_dir / "history"],
            index_file=temp_dir / ".sync-index.json",
        )
        return SyncEngine(
            client=mock_client,
            config=config,
        )

    def test_init(self, sync_engine, temp_dir, mock_client):
        """Test initialization."""
        assert sync_engine.client == mock_client
        assert sync_engine.config.namespace == "test-persona"
        assert isinstance(sync_engine.local_index, LocalIndex)

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
        # Include the uploaded file in the returned manifest
        mock_file_metadata = FileMetadata(
            md5="mock_md5",
            last_modified=datetime.now(timezone.utc),
            size=len(content),
            version=1001,
            is_deleted=False,
        )
        mock_sync_index = SyncIndexResponse(
            namespace="test",
            files={"memory/test.md": mock_file_metadata},
            index_last_modified="2024-01-01T00:00:00Z",
            index_version=1,
        )
        mock_client.write_blob.return_value = (True, "mock_md5", 1001, mock_sync_index)

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
        # Include the tombstone in the returned manifest
        mock_tombstone = FileMetadata(
            md5="",
            last_modified=datetime.now(timezone.utc),
            size=0,
            version=1001,
            is_deleted=True,
        )
        mock_sync_index = SyncIndexResponse(
            namespace="test",
            files={"memory/test.md": mock_tombstone},
            index_last_modified="2024-01-01T00:00:00Z",
            index_version=1,
        )
        mock_client.delete_blob.return_value = (1001, mock_sync_index)

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
        mock_sync_index = SyncIndexResponse(
            namespace="test",
            files={},
            index_last_modified="2024-01-01T00:00:00Z",
            index_version=1,
        )
        mock_client.write_blob.return_value = (True, "mock_md5", 1001, mock_sync_index)

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

        files = sync_engine._scan_local_files()

        # Should find files in configured scan paths (memory/ and history/)
        assert "memory/test1.md" in files
        assert "memory/test2.md" in files
        assert "history/session.json" in files

        # Should not include sync metadata files
        assert ".sync-index.json" not in files
        assert ".sync-log.jsonl" not in files
        assert ".sync-index-memory.json" not in files
        assert ".sync-log-memory.jsonl" not in files

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
