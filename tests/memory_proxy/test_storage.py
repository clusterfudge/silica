"""Tests for S3Storage class."""

import json
from datetime import datetime, timezone

import pytest

from silica.memory_proxy.models import FileMetadata
from silica.memory_proxy.storage import (
    FileNotFoundError,
    PreconditionFailedError,
    S3Storage,
)


def test_health_check_success(mock_s3):
    """Test health check with accessible S3."""
    storage = S3Storage()
    assert storage.health_check() is True


def test_health_check_with_existing_index(mock_s3):
    """Test health check when sync index exists."""
    storage = S3Storage()

    # Create sync index
    index_data = {
        "files": {},
        "index_last_modified": datetime.now(timezone.utc).isoformat(),
    }
    mock_s3.put_object(
        Bucket="test-bucket",
        Key="memory/.sync-index.json",
        Body=json.dumps(index_data).encode("utf-8"),
    )

    assert storage.health_check() is True


def test_write_new_file(mock_s3):
    """Test writing a new file."""
    storage = S3Storage()
    content = b"Hello, World!"

    is_new, md5, version, _ = storage.write_file("default", "test/file.txt", content)

    assert is_new is True
    assert md5 == "65a8e27d8879283831b664bd8b7f0ad4"
    assert version > 0  # Version is milliseconds since epoch
    assert isinstance(version, int)

    # Verify file exists in S3
    response = mock_s3.get_object(
        Bucket="test-bucket", Key="memory/default/test/file.txt"
    )
    assert response["Body"].read() == content
    assert response["Metadata"]["content-md5"] == md5


def test_write_update_file(mock_s3):
    """Test updating an existing file."""
    storage = S3Storage()

    # Write initial file
    initial_content = b"Initial content"
    is_new, initial_md5, initial_version, _ = storage.write_file(
        "default", "test/file.txt", initial_content
    )
    assert is_new is True
    assert initial_version > 0

    # Update file
    updated_content = b"Updated content"
    is_new, updated_md5, updated_version, _ = storage.write_file(
        "default", "test/file.txt", updated_content
    )

    assert is_new is False
    assert updated_md5 != initial_md5
    assert updated_version > initial_version

    # Verify updated content
    response = mock_s3.get_object(
        Bucket="test-bucket", Key="memory/default/test/file.txt"
    )
    assert response["Body"].read() == updated_content


def test_write_conditional_new_file_success(mock_s3):
    """Test conditional write for new file (using version 0)."""
    storage = S3Storage()
    content = b"New file"

    is_new, md5, version, _ = storage.write_file(
        "default", "test/file.txt", content, expected_version=0
    )

    assert is_new is True
    assert version > 0


def test_write_conditional_new_file_fails_if_exists(mock_s3):
    """Test conditional write for new file fails if file already exists."""
    storage = S3Storage()

    # Create file first
    storage.write_file("default", "test/file.txt", b"Existing content")

    # Try to create again with version 0
    with pytest.raises(PreconditionFailedError) as exc_info:
        storage.write_file(
            "default", "test/file.txt", b"New content", expected_version=0
        )

    assert "already exists" in str(exc_info.value).lower()


def test_write_conditional_update_success(mock_s3):
    """Test conditional update with correct version."""
    storage = S3Storage()

    # Create file
    content1 = b"Version 1"
    _, md5_1, version_1, _ = storage.write_file("default", "test/file.txt", content1)
    assert version_1 > 0

    # Update with correct version
    content2 = b"Version 2"
    is_new, md5_2, version_2, _ = storage.write_file(
        "default", "test/file.txt", content2, expected_version=version_1
    )

    assert is_new is False
    assert md5_2 != md5_1
    assert version_2 > version_1


def test_write_conditional_update_fails_with_wrong_version(mock_s3):
    """Test conditional update fails with incorrect version."""
    storage = S3Storage()

    # Create file
    _, _, version_1, _ = storage.write_file("default", "test/file.txt", b"Version 1")

    # Try to update with wrong version
    wrong_version = version_1 - 1000  # Use a different version
    with pytest.raises(PreconditionFailedError) as exc_info:
        storage.write_file(
            "default", "test/file.txt", b"Version 2", expected_version=wrong_version
        )

    assert exc_info.value.provided_version == str(wrong_version)


def test_write_conditional_update_fails_if_file_missing(mock_s3):
    """Test conditional update fails if expecting file to exist but it doesn't."""
    storage = S3Storage()

    with pytest.raises(PreconditionFailedError) as exc_info:
        storage.write_file(
            "default", "test/file.txt", b"Content", expected_version=12345
        )

    assert "does not exist" in str(exc_info.value).lower()
    assert exc_info.value.current_version == "none"


def test_read_file(mock_s3):
    """Test reading a file."""
    storage = S3Storage()

    # Write file
    content = b"Test content"
    _, expected_md5, expected_version, _ = storage.write_file(
        "default", "test/file.txt", content
    )

    # Read file
    read_content, md5, last_modified, content_type, version = storage.read_file(
        "default", "test/file.txt"
    )

    assert read_content == content
    assert md5 == expected_md5
    assert isinstance(last_modified, datetime)
    assert content_type == "application/octet-stream"
    assert version == expected_version


def test_read_file_not_found(mock_s3):
    """Test reading non-existent file."""
    storage = S3Storage()

    with pytest.raises(FileNotFoundError):
        storage.read_file("default", "nonexistent/file.txt")


def test_read_tombstoned_file(mock_s3):
    """Test reading a tombstoned file returns 404."""
    storage = S3Storage()

    # Create and delete file
    storage.write_file("default", "test/file.txt", b"Content")
    storage.delete_file("default", "test/file.txt")

    # Try to read tombstoned file
    with pytest.raises(FileNotFoundError) as exc_info:
        storage.read_file("default", "test/file.txt")

    assert "deleted" in str(exc_info.value).lower()


def test_delete_file(mock_s3):
    """Test deleting a file creates tombstone."""
    storage = S3Storage()

    # Create file
    content = b"Content to delete"
    _, original_md5, _, _ = storage.write_file("default", "test/file.txt", content)

    # Delete file
    storage.delete_file("default", "test/file.txt")

    # Verify tombstone exists
    response = mock_s3.get_object(
        Bucket="test-bucket", Key="memory/default/test/file.txt"
    )
    assert response["Body"].read() == b""  # Empty content
    assert response["Metadata"]["is-deleted"] == "true"
    assert response["Metadata"]["content-md5"] == original_md5


def test_delete_file_not_found(mock_s3):
    """Test deleting non-existent file."""
    storage = S3Storage()

    with pytest.raises(FileNotFoundError):
        storage.delete_file("default", "nonexistent/file.txt")


def test_delete_conditional_success(mock_s3):
    """Test conditional delete with correct version."""
    storage = S3Storage()

    # Create file
    _, md5, version, _ = storage.write_file("default", "test/file.txt", b"Content")

    # Delete with correct version
    storage.delete_file("default", "test/file.txt", expected_version=version)

    # Verify tombstone
    response = mock_s3.get_object(
        Bucket="test-bucket", Key="memory/default/test/file.txt"
    )
    assert response["Metadata"]["is-deleted"] == "true"


def test_delete_conditional_fails_with_wrong_version(mock_s3):
    """Test conditional delete fails with incorrect version."""
    storage = S3Storage()

    # Create file
    _, _, version, _ = storage.write_file("default", "test/file.txt", b"Content")

    # Try to delete with wrong version
    wrong_version = version - 1000
    with pytest.raises(PreconditionFailedError) as exc_info:
        storage.delete_file("default", "test/file.txt", expected_version=wrong_version)

    assert exc_info.value.provided_version == str(wrong_version)


def test_get_sync_index_empty(mock_s3):
    """Test getting sync index when no files exist."""
    storage = S3Storage()

    index = storage.get_sync_index("default")

    assert index.files == {}
    assert isinstance(index.index_last_modified, datetime)


def test_get_sync_index_with_files(mock_s3):
    """Test getting sync index after writing files."""
    storage = S3Storage()

    # Write multiple files
    storage.write_file("default", "file1.txt", b"Content 1")
    storage.write_file("default", "file2.txt", b"Content 2")
    storage.write_file("default", "dir/file3.txt", b"Content 3")

    # Get index
    index = storage.get_sync_index("default")

    assert len(index.files) == 3
    assert "file1.txt" in index.files
    assert "file2.txt" in index.files
    assert "dir/file3.txt" in index.files

    # Check metadata structure
    for path, metadata in index.files.items():
        assert isinstance(metadata, FileMetadata)
        assert metadata.md5
        assert isinstance(metadata.last_modified, datetime)
        assert metadata.size > 0
        assert metadata.is_deleted is False


def test_get_sync_index_includes_tombstones(mock_s3):
    """Test sync index includes tombstoned files."""
    storage = S3Storage()

    # Write and delete file
    storage.write_file("default", "deleted.txt", b"To be deleted")
    storage.delete_file("default", "deleted.txt")

    # Write active file
    storage.write_file("default", "active.txt", b"Active content")

    # Get index
    index = storage.get_sync_index("default")

    assert len(index.files) == 2
    assert index.files["deleted.txt"].is_deleted is True
    assert index.files["active.txt"].is_deleted is False


def test_sync_index_updates_after_operations(mock_s3):
    """Test sync index updates after each operation."""
    storage = S3Storage()

    # Initial state
    index1 = storage.get_sync_index("default")
    assert len(index1.files) == 0

    # After write
    storage.write_file("default", "file.txt", b"Content")
    index2 = storage.get_sync_index("default")
    assert len(index2.files) == 1
    assert index2.index_last_modified > index1.index_last_modified

    # After delete
    storage.delete_file("default", "file.txt")
    index3 = storage.get_sync_index("default")
    assert len(index3.files) == 1
    assert index3.files["file.txt"].is_deleted is True
    assert index3.index_last_modified > index2.index_last_modified


def test_make_key_with_prefix(mock_s3):
    """Test key generation with prefix."""
    storage = S3Storage()

    key = storage._make_key("default", "path/to/file.txt")
    assert key == "memory/default/path/to/file.txt"


def test_make_key_strips_leading_slash(mock_s3):
    """Test key generation strips leading slash."""
    storage = S3Storage()

    key = storage._make_key("default", "/path/to/file.txt")
    assert key == "memory/default/path/to/file.txt"


def test_calculate_md5(mock_s3):
    """Test MD5 calculation."""
    storage = S3Storage()

    content = b"Hello, World!"
    md5 = storage._calculate_md5(content)

    assert md5 == "65a8e27d8879283831b664bd8b7f0ad4"


def test_version_increases_on_updates(mock_s3):
    """Test that version number increases with each update."""
    storage = S3Storage()

    # Create file
    _, _, version1, _ = storage.write_file("default", "test/file.txt", b"Version 1")
    assert version1 > 0

    # First update
    _, _, version2, _ = storage.write_file("default", "test/file.txt", b"Version 2")
    assert version2 > version1

    # Second update
    _, _, version3, _ = storage.write_file("default", "test/file.txt", b"Version 3")
    assert version3 > version2

    # Third update
    _, _, version4, _ = storage.write_file("default", "test/file.txt", b"Version 4")
    assert version4 > version3

    # Verify version is returned on read
    _, _, _, _, read_version = storage.read_file("default", "test/file.txt")
    assert read_version == version4


def test_version_tracked_in_sync_index(mock_s3):
    """Test that version is tracked in sync index."""
    storage = S3Storage()

    # Create file
    _, _, v1, _ = storage.write_file("default", "file1.txt", b"Content 1")

    # Update multiple times
    _, _, v2, _ = storage.write_file("default", "file1.txt", b"Content 1 updated")
    _, _, v3, _ = storage.write_file("default", "file1.txt", b"Content 1 updated again")

    # Create another file and update once
    _, _, v4, _ = storage.write_file("default", "file2.txt", b"Content 2")
    _, _, v5, _ = storage.write_file("default", "file2.txt", b"Content 2 updated")

    # Get sync index
    index = storage.get_sync_index("default")

    # Check versions in index match the latest writes
    assert index.files["file1.txt"].version == v3
    assert index.files["file2.txt"].version == v5
    # Verify versions increased
    assert v2 > v1
    assert v3 > v2
    assert v5 > v4


def test_namespace_isolation(mock_s3):
    """Test that namespaces are isolated from each other."""
    storage = S3Storage()

    # Create file in namespace1
    storage.write_file("namespace1", "shared-name.txt", b"Content in namespace1")

    # Create file with same name in namespace2
    storage.write_file("namespace2", "shared-name.txt", b"Content in namespace2")

    # Verify namespace1 file
    content1, _, _, _, _ = storage.read_file("namespace1", "shared-name.txt")
    assert content1 == b"Content in namespace1"

    # Verify namespace2 file
    content2, _, _, _, _ = storage.read_file("namespace2", "shared-name.txt")
    assert content2 == b"Content in namespace2"

    # Get sync indexes for each namespace
    index1 = storage.get_sync_index("namespace1")
    index2 = storage.get_sync_index("namespace2")

    # Each namespace should only see its own file
    assert len(index1.files) == 1
    assert "shared-name.txt" in index1.files
    assert len(index2.files) == 1
    assert "shared-name.txt" in index2.files

    # Delete file in namespace1
    storage.delete_file("namespace1", "shared-name.txt")

    # Verify namespace1 file is tombstoned
    with pytest.raises(FileNotFoundError):
        storage.read_file("namespace1", "shared-name.txt")

    # Verify namespace2 file is still accessible
    content2_again, _, _, _, _ = storage.read_file("namespace2", "shared-name.txt")
    assert content2_again == b"Content in namespace2"

    # Check sync indexes again
    index1_after = storage.get_sync_index("namespace1")
    index2_after = storage.get_sync_index("namespace2")

    assert index1_after.files["shared-name.txt"].is_deleted is True
    assert index2_after.files["shared-name.txt"].is_deleted is False
