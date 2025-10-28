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

    is_new, md5 = storage.write_file("test/file.txt", content)

    assert is_new is True
    assert md5 == "65a8e27d8879283831b664bd8b7f0ad4"

    # Verify file exists in S3
    response = mock_s3.get_object(Bucket="test-bucket", Key="memory/test/file.txt")
    assert response["Body"].read() == content
    assert response["Metadata"]["content-md5"] == md5


def test_write_update_file(mock_s3):
    """Test updating an existing file."""
    storage = S3Storage()

    # Write initial file
    initial_content = b"Initial content"
    is_new, initial_md5 = storage.write_file("test/file.txt", initial_content)
    assert is_new is True

    # Update file
    updated_content = b"Updated content"
    is_new, updated_md5 = storage.write_file("test/file.txt", updated_content)

    assert is_new is False
    assert updated_md5 != initial_md5

    # Verify updated content
    response = mock_s3.get_object(Bucket="test-bucket", Key="memory/test/file.txt")
    assert response["Body"].read() == updated_content


def test_write_conditional_new_file_success(mock_s3):
    """Test conditional write for new file (using 'new' sentinel)."""
    storage = S3Storage()
    content = b"New file"

    is_new, md5 = storage.write_file("test/file.txt", content, expected_md5="new")

    assert is_new is True


def test_write_conditional_new_file_fails_if_exists(mock_s3):
    """Test conditional write for new file fails if file already exists."""
    storage = S3Storage()

    # Create file first
    storage.write_file("test/file.txt", b"Existing content")

    # Try to create again with 'new' sentinel
    with pytest.raises(PreconditionFailedError) as exc_info:
        storage.write_file("test/file.txt", b"New content", expected_md5="new")

    assert "already exists" in str(exc_info.value).lower()


def test_write_conditional_update_success(mock_s3):
    """Test conditional update with correct MD5."""
    storage = S3Storage()

    # Create file
    content1 = b"Version 1"
    _, md5_1 = storage.write_file("test/file.txt", content1)

    # Update with correct MD5
    content2 = b"Version 2"
    is_new, md5_2 = storage.write_file("test/file.txt", content2, expected_md5=md5_1)

    assert is_new is False
    assert md5_2 != md5_1


def test_write_conditional_update_fails_with_wrong_md5(mock_s3):
    """Test conditional update fails with incorrect MD5."""
    storage = S3Storage()

    # Create file
    storage.write_file("test/file.txt", b"Version 1")

    # Try to update with wrong MD5
    with pytest.raises(PreconditionFailedError) as exc_info:
        storage.write_file("test/file.txt", b"Version 2", expected_md5="wrong-md5")

    assert exc_info.value.provided_md5 == "wrong-md5"


def test_write_conditional_update_fails_if_file_missing(mock_s3):
    """Test conditional update fails if expecting file to exist but it doesn't."""
    storage = S3Storage()

    with pytest.raises(PreconditionFailedError) as exc_info:
        storage.write_file("test/file.txt", b"Content", expected_md5="some-md5")

    assert "does not exist" in str(exc_info.value).lower()
    assert exc_info.value.current_md5 == "none"


def test_read_file(mock_s3):
    """Test reading a file."""
    storage = S3Storage()

    # Write file
    content = b"Test content"
    _, expected_md5 = storage.write_file("test/file.txt", content)

    # Read file
    read_content, md5, last_modified, content_type = storage.read_file("test/file.txt")

    assert read_content == content
    assert md5 == expected_md5
    assert isinstance(last_modified, datetime)
    assert content_type == "application/octet-stream"


def test_read_file_not_found(mock_s3):
    """Test reading non-existent file."""
    storage = S3Storage()

    with pytest.raises(FileNotFoundError):
        storage.read_file("nonexistent/file.txt")


def test_read_tombstoned_file(mock_s3):
    """Test reading a tombstoned file returns 404."""
    storage = S3Storage()

    # Create and delete file
    storage.write_file("test/file.txt", b"Content")
    storage.delete_file("test/file.txt")

    # Try to read tombstoned file
    with pytest.raises(FileNotFoundError) as exc_info:
        storage.read_file("test/file.txt")

    assert "deleted" in str(exc_info.value).lower()


def test_delete_file(mock_s3):
    """Test deleting a file creates tombstone."""
    storage = S3Storage()

    # Create file
    content = b"Content to delete"
    _, original_md5 = storage.write_file("test/file.txt", content)

    # Delete file
    storage.delete_file("test/file.txt")

    # Verify tombstone exists
    response = mock_s3.get_object(Bucket="test-bucket", Key="memory/test/file.txt")
    assert response["Body"].read() == b""  # Empty content
    assert response["Metadata"]["is-deleted"] == "true"
    assert response["Metadata"]["content-md5"] == original_md5


def test_delete_file_not_found(mock_s3):
    """Test deleting non-existent file."""
    storage = S3Storage()

    with pytest.raises(FileNotFoundError):
        storage.delete_file("nonexistent/file.txt")


def test_delete_conditional_success(mock_s3):
    """Test conditional delete with correct MD5."""
    storage = S3Storage()

    # Create file
    _, md5 = storage.write_file("test/file.txt", b"Content")

    # Delete with correct MD5
    storage.delete_file("test/file.txt", expected_md5=md5)

    # Verify tombstone
    response = mock_s3.get_object(Bucket="test-bucket", Key="memory/test/file.txt")
    assert response["Metadata"]["is-deleted"] == "true"


def test_delete_conditional_fails_with_wrong_md5(mock_s3):
    """Test conditional delete fails with incorrect MD5."""
    storage = S3Storage()

    # Create file
    storage.write_file("test/file.txt", b"Content")

    # Try to delete with wrong MD5
    with pytest.raises(PreconditionFailedError) as exc_info:
        storage.delete_file("test/file.txt", expected_md5="wrong-md5")

    assert exc_info.value.provided_md5 == "wrong-md5"


def test_get_sync_index_empty(mock_s3):
    """Test getting sync index when no files exist."""
    storage = S3Storage()

    index = storage.get_sync_index()

    assert index.files == {}
    assert isinstance(index.index_last_modified, datetime)


def test_get_sync_index_with_files(mock_s3):
    """Test getting sync index after writing files."""
    storage = S3Storage()

    # Write multiple files
    storage.write_file("file1.txt", b"Content 1")
    storage.write_file("file2.txt", b"Content 2")
    storage.write_file("dir/file3.txt", b"Content 3")

    # Get index
    index = storage.get_sync_index()

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
    storage.write_file("deleted.txt", b"To be deleted")
    storage.delete_file("deleted.txt")

    # Write active file
    storage.write_file("active.txt", b"Active content")

    # Get index
    index = storage.get_sync_index()

    assert len(index.files) == 2
    assert index.files["deleted.txt"].is_deleted is True
    assert index.files["active.txt"].is_deleted is False


def test_sync_index_updates_after_operations(mock_s3):
    """Test sync index updates after each operation."""
    storage = S3Storage()

    # Initial state
    index1 = storage.get_sync_index()
    assert len(index1.files) == 0

    # After write
    storage.write_file("file.txt", b"Content")
    index2 = storage.get_sync_index()
    assert len(index2.files) == 1
    assert index2.index_last_modified > index1.index_last_modified

    # After delete
    storage.delete_file("file.txt")
    index3 = storage.get_sync_index()
    assert len(index3.files) == 1
    assert index3.files["file.txt"].is_deleted is True
    assert index3.index_last_modified > index2.index_last_modified


def test_make_key_with_prefix(mock_s3):
    """Test key generation with prefix."""
    storage = S3Storage()

    key = storage._make_key("path/to/file.txt")
    assert key == "memory/path/to/file.txt"


def test_make_key_strips_leading_slash(mock_s3):
    """Test key generation strips leading slash."""
    storage = S3Storage()

    key = storage._make_key("/path/to/file.txt")
    assert key == "memory/path/to/file.txt"


def test_calculate_md5(mock_s3):
    """Test MD5 calculation."""
    storage = S3Storage()

    content = b"Hello, World!"
    md5 = storage._calculate_md5(content)

    assert md5 == "65a8e27d8879283831b664bd8b7f0ad4"
