"""Tests for memory sync bootstrap scenarios.

These tests verify that the sync engine handles bootstrap scenarios correctly,
specifically that it NEVER deletes local files without an explicit tombstone.

The core principle: Remote is authoritative, local is a cache.
Only explicit tombstones (remote_entry.is_deleted == true) should trigger local deletion.
"""

import hashlib
import pytest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from silica.developer.memory.sync import (
    SyncEngine,
)
from silica.developer.memory.proxy_client import (
    FileMetadata,
    MemoryProxyClient,
    SyncIndexResponse,
)


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


def calculate_md5(content: bytes) -> str:
    """Calculate MD5 hash of content."""
    return hashlib.md5(content).hexdigest()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_client():
    """Create a mock MemoryProxyClient."""
    return MagicMock(spec=MemoryProxyClient)


@pytest.fixture
def sync_engine(temp_dir, mock_client):
    """Create a SyncEngine instance."""
    return SyncEngine(
        client=mock_client,
        local_base_dir=temp_dir,
        namespace="test-persona",
    )


class TestBootstrapEmptyIndex:
    """Tests for bootstrap scenarios with empty local index.

    These tests verify that when the local index is empty (first sync or lost index),
    the sync engine makes safe decisions.
    """

    def test_bootstrap_with_local_files_only(self, sync_engine, mock_client, temp_dir):
        """Bootstrap: Empty index, local files exist, no remote files.

        Expected: Upload all local files (they're new).
        """
        # Create local files
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        (memory_dir / "file1.md").write_text("local content 1")
        (memory_dir / "file2.md").write_text("local content 2")

        # Configure mock: empty remote
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should upload both files
        assert len(plan.upload) == 2
        assert len(plan.download) == 0
        assert len(plan.delete_local) == 0
        assert len(plan.delete_remote) == 0
        assert len(plan.conflicts) == 0

        upload_paths = {op.path for op in plan.upload}
        assert "memory/file1.md" in upload_paths
        assert "memory/file2.md" in upload_paths

        # All should be marked as "New local file"
        assert all(op.reason == "New local file" for op in plan.upload)

    def test_bootstrap_with_remote_files_only(self, sync_engine, mock_client, temp_dir):
        """Bootstrap: Empty index, no local files, remote files exist.

        Expected: Download all remote files (they're new).
        """
        # No local files (just create memory dir)
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()

        # Configure mock: remote has files
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/remote1.md",
                    "md5": "abc123",
                    "size": 100,
                    "version": 1000,
                    "last_modified": "2025-01-01T00:00:00+00:00",
                    "is_deleted": False,
                },
                {
                    "path": "memory/remote2.md",
                    "md5": "def456",
                    "size": 200,
                    "version": 1001,
                    "last_modified": "2025-01-01T00:00:00+00:00",
                    "is_deleted": False,
                },
            ]
        )

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should download both files
        assert len(plan.upload) == 0
        assert len(plan.download) == 2
        assert len(plan.delete_local) == 0
        assert len(plan.delete_remote) == 0
        assert len(plan.conflicts) == 0

        download_paths = {op.path for op in plan.download}
        assert "memory/remote1.md" in download_paths
        assert "memory/remote2.md" in download_paths

        # All should be marked as "New remote file"
        assert all(op.reason == "New remote file" for op in plan.download)

    def test_bootstrap_with_both_different_files(
        self, sync_engine, mock_client, temp_dir
    ):
        """Bootstrap: Empty index, different files on local and remote.

        Expected: Upload local, download remote (merge both sides).
        """
        # Create local files
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        (memory_dir / "local_only.md").write_text("local content")

        # Configure mock: remote has different file
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/remote_only.md",
                    "md5": "abc123",
                    "size": 100,
                    "version": 1000,
                    "last_modified": "2025-01-01T00:00:00+00:00",
                    "is_deleted": False,
                },
            ]
        )

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should upload local file and download remote file
        assert len(plan.upload) == 1
        assert len(plan.download) == 1
        assert len(plan.delete_local) == 0
        assert len(plan.delete_remote) == 0
        assert len(plan.conflicts) == 0

        assert plan.upload[0].path == "memory/local_only.md"
        assert plan.download[0].path == "memory/remote_only.md"

    def test_bootstrap_with_same_file_different_content(
        self, sync_engine, mock_client, temp_dir
    ):
        """Bootstrap: Empty index, same file exists on both sides with different content.

        Expected: Since there's no index entry, remote is authority. Download remote.
        This matches the principle: "Remote is authoritative, local is cache."
        """
        # Create local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        local_content = b"local content"
        (memory_dir / "file.md").write_bytes(local_content)

        # Configure mock: remote has same file with different content
        remote_md5 = "remote_md5_different"
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/file.md",
                    "md5": remote_md5,
                    "size": 200,
                    "version": 1000,
                    "last_modified": "2025-01-01T00:00:00+00:00",
                    "is_deleted": False,
                },
            ]
        )

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Since index is empty, we have no history. Remote is authority.
        # Should download remote version (overwrite local)
        assert len(plan.download) == 1
        assert len(plan.upload) == 0
        assert len(plan.delete_local) == 0
        assert len(plan.conflicts) == 0

        assert plan.download[0].path == "memory/file.md"
        assert plan.download[0].reason == "Remote is authority, bootstrap scenario"


class TestBootstrapWithStaleIndex:
    """Tests for bootstrap scenarios with stale/old local index.

    These tests verify the CRITICAL bug: when local index exists but remote
    is empty/reset, we should NOT delete local files.
    """

    def test_stale_index_local_files_no_remote(
        self, sync_engine, mock_client, temp_dir
    ):
        """CRITICAL: Stale index, local files exist, no remote files.

        This is the MAIN BUG scenario:
        - Local index has entries (from previous sync)
        - Local files exist
        - Remote is empty (namespace reset or never uploaded)

        WRONG: Delete local files (current behavior)
        CORRECT: Upload local files (preserve user work)
        """
        # Create local files
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        content1 = b"local content 1"
        content2 = b"local content 2"
        (memory_dir / "file1.md").write_bytes(content1)
        (memory_dir / "file2.md").write_bytes(content2)

        # Setup local index with old entries (simulating previous sync)
        sync_engine.local_index.load()
        sync_engine.local_index.update_entry(
            "memory/file1.md",
            FileMetadata(
                md5=calculate_md5(content1),
                last_modified=datetime.now(timezone.utc),
                size=len(content1),
                version=500,  # Old version
                is_deleted=False,
            ),
        )
        sync_engine.local_index.update_entry(
            "memory/file2.md",
            FileMetadata(
                md5=calculate_md5(content2),
                last_modified=datetime.now(timezone.utc),
                size=len(content2),
                version=501,  # Old version
                is_deleted=False,
            ),
        )
        sync_engine.local_index.save()

        # Configure mock: empty remote (namespace reset)
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # MUST NOT delete local files!
        assert (
            len(plan.delete_local) == 0
        ), "CRITICAL: Must not delete local files without tombstone"

        # Should upload both files (re-upload to remote)
        assert len(plan.upload) == 2
        assert len(plan.download) == 0
        assert len(plan.delete_remote) == 0

        upload_paths = {op.path for op in plan.upload}
        assert "memory/file1.md" in upload_paths
        assert "memory/file2.md" in upload_paths

        # Reason should indicate re-upload
        for op in plan.upload:
            assert "upload" in op.reason.lower() or "local" in op.reason.lower()


class TestTombstoneHandling:
    """Tests for explicit tombstone handling.

    Tombstones are the ONLY way to trigger local file deletion.
    """

    def test_tombstone_deletes_local_file(self, sync_engine, mock_client, temp_dir):
        """Tombstone in remote index should delete local file.

        This is the ONLY scenario where local files should be deleted.
        """
        # Create local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        content = b"local content"
        (memory_dir / "file.md").write_bytes(content)

        # Setup local index
        sync_engine.local_index.load()
        sync_engine.local_index.update_entry(
            "memory/file.md",
            FileMetadata(
                md5=calculate_md5(content),
                last_modified=datetime.now(timezone.utc),
                size=len(content),
                version=1000,
                is_deleted=False,
            ),
        )
        sync_engine.local_index.save()

        # Configure mock: remote has tombstone
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/file.md",
                    "md5": calculate_md5(content),
                    "size": 0,
                    "version": 1001,  # Newer version
                    "last_modified": "2025-01-02T00:00:00+00:00",
                    "is_deleted": True,  # TOMBSTONE
                },
            ]
        )

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should delete local file
        assert len(plan.delete_local) == 1
        assert len(plan.upload) == 0
        assert len(plan.download) == 0
        assert len(plan.conflicts) == 0

        assert plan.delete_local[0].path == "memory/file.md"
        assert (
            "delet" in plan.delete_local[0].reason.lower()
        )  # Matches "delete" or "deletion"

    def test_tombstone_on_bootstrap_deletes_local(
        self, sync_engine, mock_client, temp_dir
    ):
        """Tombstone in remote during bootstrap (no index) should delete local file.

        Even without a local index entry, an explicit tombstone means
        "this file was deleted, remove it everywhere."
        """
        # Create local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        (memory_dir / "file.md").write_text("local content")

        # NO local index entry (bootstrap scenario)

        # Configure mock: remote has tombstone
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/file.md",
                    "md5": "abc123",
                    "size": 0,
                    "version": 1000,
                    "last_modified": "2025-01-01T00:00:00+00:00",
                    "is_deleted": True,  # TOMBSTONE
                },
            ]
        )

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should delete local file (tombstone is explicit)
        assert len(plan.delete_local) == 1
        assert plan.delete_local[0].path == "memory/file.md"

    def test_no_tombstone_no_local_deletion(self, sync_engine, mock_client, temp_dir):
        """Without a tombstone, local files should NEVER be deleted.

        This is the core safety rule.
        """
        # Create local files
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        (memory_dir / "file1.md").write_text("content 1")
        (memory_dir / "file2.md").write_text("content 2")

        # Setup local index with entries
        sync_engine.local_index.load()
        for i in [1, 2]:
            sync_engine.local_index.update_entry(
                f"memory/file{i}.md",
                FileMetadata(
                    md5=f"md5_{i}",
                    last_modified=datetime.now(timezone.utc),
                    size=100,
                    version=1000 + i,
                    is_deleted=False,
                ),
            )
        sync_engine.local_index.save()

        # Configure mock: remote is empty (no tombstones)
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # MUST NOT delete any local files
        assert len(plan.delete_local) == 0, "No tombstones = no local deletion"

        # Should upload the files instead
        assert len(plan.upload) == 2


class TestConflictScenarios:
    """Tests for conflict scenarios with correct tombstone handling."""

    def test_local_file_exists_remote_tombstone_not_conflict(
        self, sync_engine, mock_client, temp_dir
    ):
        """Local file exists, remote has tombstone = not a conflict, just delete local.

        Tombstones are authoritative and unambiguous.
        """
        # Create local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        content = b"local content"
        (memory_dir / "file.md").write_bytes(content)

        # Setup local index (file was known)
        sync_engine.local_index.load()
        sync_engine.local_index.update_entry(
            "memory/file.md",
            FileMetadata(
                md5=calculate_md5(content),
                last_modified=datetime.now(timezone.utc),
                size=len(content),
                version=1000,
                is_deleted=False,
            ),
        )
        sync_engine.local_index.save()

        # Configure mock: remote has tombstone
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/file.md",
                    "md5": calculate_md5(content),
                    "size": 0,
                    "version": 1001,
                    "last_modified": "2025-01-02T00:00:00+00:00",
                    "is_deleted": True,
                },
            ]
        )

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should be a clean delete, not a conflict
        assert len(plan.delete_local) == 1
        assert len(plan.conflicts) == 0
        assert plan.delete_local[0].path == "memory/file.md"

    def test_local_deleted_remote_exists_deletes_remote(
        self, sync_engine, mock_client, temp_dir
    ):
        """Local file deleted (not present), remote exists, index has entry = delete remote.

        This indicates the user deleted the file locally.
        """
        # No local file (create empty memory dir)
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()

        # Setup local index (file was known)
        sync_engine.local_index.load()
        sync_engine.local_index.update_entry(
            "memory/file.md",
            FileMetadata(
                md5="old_md5",
                last_modified=datetime.now(timezone.utc),
                size=100,
                version=1000,
                is_deleted=False,
            ),
        )
        sync_engine.local_index.save()

        # Configure mock: remote still has file
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/file.md",
                    "md5": "old_md5",
                    "size": 100,
                    "version": 1000,
                    "last_modified": "2025-01-01T00:00:00+00:00",
                    "is_deleted": False,
                },
            ]
        )

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should delete remote (propagate local deletion)
        assert len(plan.delete_remote) == 1
        assert len(plan.delete_local) == 0
        assert len(plan.conflicts) == 0
        assert plan.delete_remote[0].path == "memory/file.md"


class TestIndexConsistency:
    """Tests for index update consistency after operations."""

    def test_index_updated_after_determining_in_sync(
        self, sync_engine, mock_client, temp_dir
    ):
        """When files are in sync, index should be updated to track current state."""
        # Create local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        content = b"content"
        (memory_dir / "file.md").write_bytes(content)
        md5 = calculate_md5(content)

        # Configure mock: remote has same file
        mock_client.get_sync_index.return_value = make_sync_index_response(
            [
                {
                    "path": "memory/file.md",
                    "md5": md5,
                    "size": len(content),
                    "version": 1000,
                    "last_modified": "2025-01-01T00:00:00+00:00",
                    "is_deleted": False,
                },
            ]
        )

        # Analyze sync (this should update index as side effect)
        plan = sync_engine.analyze_sync_operations()

        # No operations needed (in sync)
        assert plan.total_operations == 0

        # Index should have been updated
        index_entry = sync_engine.local_index.get_entry("memory/file.md")
        assert index_entry is not None
        assert index_entry.md5 == md5
        assert index_entry.version == 1000
        assert index_entry.is_deleted is False


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_empty_local_empty_remote_empty_index(
        self, sync_engine, mock_client, temp_dir
    ):
        """Complete bootstrap: nothing exists anywhere."""
        # Create empty memory dir
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()

        # Configure mock: empty remote
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # No operations needed
        assert plan.total_operations == 0

    def test_persona_file_synced_correctly(self, sync_engine, mock_client, temp_dir):
        """persona.md file in base directory should be synced."""
        # Create persona.md in base directory
        persona_content = b"# Persona\n\nMy persona"
        (temp_dir / "persona.md").write_bytes(persona_content)

        # Configure mock: empty remote
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should upload persona.md
        assert len(plan.upload) == 1
        assert plan.upload[0].path == "persona.md"

    def test_sync_metadata_files_ignored(self, sync_engine, mock_client, temp_dir):
        """Sync metadata files (.sync-index.json, .sync-log.jsonl) should not be synced."""
        # Create sync metadata files
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()
        (temp_dir / ".sync-index.json").write_text("{}")
        (temp_dir / ".sync-log.jsonl").write_text("{}\n")

        # Also create a regular file
        (memory_dir / "file.md").write_text("content")

        # Configure mock: empty remote
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # Should only upload the regular file, not metadata
        assert len(plan.upload) == 1
        assert plan.upload[0].path == "memory/file.md"

    def test_both_sides_gone_clears_index(self, sync_engine, mock_client, temp_dir):
        """When file is gone from both local and remote, clear index entry."""
        # No local file
        memory_dir = temp_dir / "memory"
        memory_dir.mkdir()

        # Setup local index with entry
        sync_engine.local_index.load()
        sync_engine.local_index.update_entry(
            "memory/file.md",
            FileMetadata(
                md5="old_md5",
                last_modified=datetime.now(timezone.utc),
                size=100,
                version=1000,
                is_deleted=False,
            ),
        )
        sync_engine.local_index.save()

        # Configure mock: remote doesn't have file either
        mock_client.get_sync_index.return_value = make_sync_index_response([])

        # Analyze sync
        plan = sync_engine.analyze_sync_operations()

        # This is ambiguous - file could have been deleted locally or remotely
        # Safe default: upload (re-create on remote if needed)
        # But since file doesn't exist locally, nothing to upload
        # Should just not have any operations
        assert plan.total_operations == 0
