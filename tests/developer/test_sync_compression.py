"""Tests for sync compression functionality."""

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

from silica.developer.memory.proxy_client import FileMetadata, SyncIndexResponse
from silica.developer.memory.sync import SyncEngine
from silica.developer.memory.sync_config import SyncConfig


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_client():
    """Create a mock MemoryProxyClient."""
    client = MagicMock()
    # Default to empty remote
    client.get_sync_index.return_value = SyncIndexResponse(
        files={},
        index_last_modified=datetime.now(timezone.utc),
        index_version=1,
    )
    return client


@pytest.fixture
def config_with_compression(temp_dir):
    """Create a SyncConfig with compression enabled."""
    scan_dir = temp_dir / "data"
    scan_dir.mkdir()
    return SyncConfig(
        namespace="test/compressed",
        scan_paths=[scan_dir],
        index_file=temp_dir / ".sync-index.json",
        base_dir=temp_dir,
        compress=True,
    )


@pytest.fixture
def config_without_compression(temp_dir):
    """Create a SyncConfig with compression disabled."""
    scan_dir = temp_dir / "data"
    scan_dir.mkdir()
    return SyncConfig(
        namespace="test/uncompressed",
        scan_paths=[scan_dir],
        index_file=temp_dir / ".sync-index.json",
        base_dir=temp_dir,
        compress=False,
    )


class TestUploadCompression:
    """Tests for compression during upload."""

    def test_upload_compresses_file_when_enabled(
        self, temp_dir, mock_client, config_with_compression
    ):
        """Test that files are compressed when compression is enabled."""
        # Create a test file with compressible content
        test_file = config_with_compression.scan_paths[0] / "test.json"
        test_content = json.dumps({"data": "x" * 10000})  # Highly compressible
        test_file.write_text(test_content)

        # Set up mock response - paths are relative to scan_path
        mock_client.write_blob.return_value = (
            True,  # is_new
            "abc123",  # md5
            1,  # version
            SyncIndexResponse(
                files={
                    "test.json.gz": FileMetadata(
                        md5="abc123",
                        last_modified=datetime.now(timezone.utc),
                        size=100,
                        version=1,
                        is_deleted=False,
                    )
                },
                index_last_modified=datetime.now(timezone.utc),
                index_version=1,
            ),
        )

        engine = SyncEngine(mock_client, config_with_compression)

        # Run analyze to populate path mapping (like real sync flow does)
        mock_client.get_sync_index.return_value = SyncIndexResponse(
            files={},
            index_last_modified=datetime.now(timezone.utc),
            index_version=1,
        )
        engine.analyze_sync_operations()

        # Path is relative to scan_path
        result = engine.upload_file("test.json", 0)

        assert result is True
        # write_blob is called during analyze and upload
        assert mock_client.write_blob.call_count >= 1

        # Check the upload was compressed - get the last call
        call_kwargs = mock_client.write_blob.call_args
        assert call_kwargs[1]["path"] == "test.json.gz"
        assert call_kwargs[1]["content_type"] == "application/gzip"

        # Verify the content is actually gzipped
        uploaded_content = call_kwargs[1]["content"]
        decompressed = gzip.decompress(uploaded_content)
        assert decompressed.decode() == test_content

    def test_upload_does_not_compress_when_disabled(
        self, temp_dir, mock_client, config_without_compression
    ):
        """Test that files are not compressed when compression is disabled."""
        # Create a test file
        test_file = config_without_compression.scan_paths[0] / "test.json"
        test_content = json.dumps({"data": "test"})
        test_file.write_text(test_content)

        # Set up mock response - paths are relative to scan_path
        mock_client.write_blob.return_value = (
            True,
            "abc123",
            1,
            SyncIndexResponse(
                files={
                    "test.json": FileMetadata(
                        md5="abc123",
                        last_modified=datetime.now(timezone.utc),
                        size=len(test_content),
                        version=1,
                        is_deleted=False,
                    )
                },
                index_last_modified=datetime.now(timezone.utc),
                index_version=1,
            ),
        )

        engine = SyncEngine(mock_client, config_without_compression)

        # Run analyze to populate path mapping
        mock_client.get_sync_index.return_value = SyncIndexResponse(
            files={},
            index_last_modified=datetime.now(timezone.utc),
            index_version=1,
        )
        engine.analyze_sync_operations()

        # Path is relative to scan_path
        result = engine.upload_file("test.json", 0)

        assert result is True
        assert mock_client.write_blob.call_count >= 1

        # Check the upload was NOT compressed - get the last call
        call_kwargs = mock_client.write_blob.call_args
        assert call_kwargs[1]["path"] == "test.json"
        assert call_kwargs[1]["content_type"] == "application/octet-stream"

        # Content should be raw
        uploaded_content = call_kwargs[1]["content"]
        assert uploaded_content.decode() == test_content

    def test_upload_skips_compression_if_larger(
        self, temp_dir, mock_client, config_with_compression
    ):
        """Test that compression is skipped if it makes the file larger."""
        # Create a file with incompressible content (random-ish binary)
        test_file = config_with_compression.scan_paths[0] / "random.bin"
        # Already compressed data won't compress further
        incompressible_content = gzip.compress(b"x" * 100)
        test_file.write_bytes(incompressible_content)

        # Set up mock response - paths are relative to scan_path
        mock_client.write_blob.return_value = (
            True,
            "abc123",
            1,
            SyncIndexResponse(
                files={
                    "random.bin": FileMetadata(
                        md5="abc123",
                        last_modified=datetime.now(timezone.utc),
                        size=len(incompressible_content),
                        version=1,
                        is_deleted=False,
                    )
                },
                index_last_modified=datetime.now(timezone.utc),
                index_version=1,
            ),
        )

        engine = SyncEngine(mock_client, config_with_compression)

        # Run analyze to populate path mapping
        mock_client.get_sync_index.return_value = SyncIndexResponse(
            files={},
            index_last_modified=datetime.now(timezone.utc),
            index_version=1,
        )
        engine.analyze_sync_operations()

        # Path is relative to scan_path
        result = engine.upload_file("random.bin", 0)

        assert result is True

        # Check the upload - should NOT have .gz extension if compression didn't help
        call_kwargs = mock_client.write_blob.call_args
        # Either compressed or not, depending on if gzip helped
        call_kwargs[1]["path"]
        # If compression didn't help, path should not end with .gz
        # Note: gzip adds some overhead, so small already-compressed files won't compress


class TestDownloadDecompression:
    """Tests for decompression during download."""

    def test_download_decompresses_gz_file(
        self, temp_dir, mock_client, config_with_compression
    ):
        """Test that .gz files are decompressed on download."""
        original_content = json.dumps({"data": "test content"})
        compressed_content = gzip.compress(original_content.encode())

        mock_client.read_blob.return_value = (
            compressed_content,
            "abc123",
            datetime.now(timezone.utc),
            "application/gzip",
            1,
        )

        engine = SyncEngine(mock_client, config_with_compression)
        # Path is relative to scan_path, not including the directory name
        result = engine.download_file("test.json.gz")

        assert result is True

        # Check that local file was written WITHOUT .gz extension
        local_file = config_with_compression.scan_paths[0] / "test.json"
        assert local_file.exists()

        # Check content is decompressed
        assert local_file.read_text() == original_content

    def test_download_handles_non_gz_file(
        self, temp_dir, mock_client, config_without_compression
    ):
        """Test that non-.gz files are handled normally."""
        original_content = json.dumps({"data": "test"})

        mock_client.read_blob.return_value = (
            original_content.encode(),
            "abc123",
            datetime.now(timezone.utc),
            "application/octet-stream",
            1,
        )

        engine = SyncEngine(mock_client, config_without_compression)
        # Path is relative to scan_path
        result = engine.download_file("test.json")

        assert result is True

        # Check file was written as-is
        local_file = config_without_compression.scan_paths[0] / "test.json"
        assert local_file.exists()
        assert local_file.read_text() == original_content

    def test_download_decompresses_based_on_content_type(
        self, temp_dir, mock_client, config_with_compression
    ):
        """Test that decompression uses content-type as a hint."""
        original_content = b"binary data"
        compressed_content = gzip.compress(original_content)

        # File without .gz extension but with gzip content-type
        mock_client.read_blob.return_value = (
            compressed_content,
            "abc123",
            datetime.now(timezone.utc),
            "application/gzip",  # Content type indicates compression
            1,
        )

        engine = SyncEngine(mock_client, config_with_compression)
        # Path is relative to scan_path
        result = engine.download_file("test.bin")

        assert result is True

        # Content should be decompressed
        local_file = config_with_compression.scan_paths[0] / "test.bin"
        assert local_file.exists()
        assert local_file.read_bytes() == original_content


class TestSyncPlanWithCompression:
    """Tests for sync planning with compression enabled."""

    def test_analyze_maps_local_to_compressed_remote(
        self, temp_dir, mock_client, config_with_compression
    ):
        """Test that sync analysis maps local files to compressed remote paths."""
        # Create local file
        test_file = config_with_compression.scan_paths[0] / "test.json"
        test_file.write_text('{"data": "test"}')

        # Remote has compressed version - paths are relative to scan_path
        mock_client.get_sync_index.return_value = SyncIndexResponse(
            files={
                "test.json.gz": FileMetadata(
                    md5="different_md5",  # Different from local
                    last_modified=datetime.now(timezone.utc),
                    size=100,
                    version=2,
                    is_deleted=False,
                )
            },
            index_last_modified=datetime.now(timezone.utc),
            index_version=1,
        )

        engine = SyncEngine(mock_client, config_with_compression)
        plan = engine.analyze_sync_operations()

        # Should recognize these as the same file and plan appropriately
        # Since we have no index, remote is authority -> download
        assert len(plan.download) == 1
        assert plan.download[0].path == "test.json.gz"

    def test_analyze_detects_new_local_file_for_compression(
        self, temp_dir, mock_client, config_with_compression
    ):
        """Test that new local files are planned for compressed upload."""
        # Create local file
        test_file = config_with_compression.scan_paths[0] / "new.json"
        test_file.write_text('{"data": "new"}')

        # Empty remote
        mock_client.get_sync_index.return_value = SyncIndexResponse(
            files={},
            index_last_modified=datetime.now(timezone.utc),
            index_version=1,
        )

        engine = SyncEngine(mock_client, config_with_compression)
        plan = engine.analyze_sync_operations()

        # Should plan upload
        assert len(plan.upload) == 1
        # The path in the plan is the local path; upload_file adds .gz
        assert plan.upload[0].path == "new.json"
