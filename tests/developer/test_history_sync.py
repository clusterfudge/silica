"""Tests for history sync engine with compression."""

import gzip
import pytest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from silica.developer.memory.history_sync import (
    HistorySyncEngine,
    HistoryLocalIndex,
    HistoryPushResult,
)
from silica.developer.memory.sync_config import SyncConfig
from silica.developer.memory.proxy_client import (
    FileMetadata,
    MemoryProxyClient,
    SyncIndexResponse,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def session_dir(temp_dir, monkeypatch):
    """Create a session directory structure."""
    # Set up persona directory
    personas_dir = temp_dir / "personas"
    personas_dir.mkdir()
    persona_path = personas_dir / "test"
    persona_path.mkdir()

    # Mock personas module
    from silica.developer import personas

    monkeypatch.setattr(personas, "_PERSONAS_BASE_DIRECTORY", personas_dir)

    # Create session directory
    session_path = persona_path / "history" / "session-1"
    session_path.mkdir(parents=True)

    # Create some history files
    (session_path / "conversation.json").write_text('{"messages": []}')
    (session_path / "conversation-1.json").write_text('{"messages": ["old"]}')

    return session_path


@pytest.fixture
def mock_client():
    """Create a mock MemoryProxyClient."""
    return MagicMock(spec=MemoryProxyClient)


class TestHistoryLocalIndex:
    """Tests for HistoryLocalIndex."""

    def test_init(self, temp_dir):
        """Test index initialization."""
        index_file = temp_dir / ".sync-index.json"
        index = HistoryLocalIndex(index_file)

        assert index.index_file == index_file
        assert not index._loaded

    def test_load_empty(self, temp_dir):
        """Test loading when no index file exists."""
        index_file = temp_dir / ".sync-index.json"
        index = HistoryLocalIndex(index_file)

        entries = index.load()

        assert entries == {}
        assert index._loaded

    def test_save_and_load(self, temp_dir):
        """Test saving and loading index."""
        index_file = temp_dir / ".sync-index.json"
        index = HistoryLocalIndex(index_file)

        # Add entry
        metadata = FileMetadata(
            md5="test_md5",
            last_modified=datetime.now(timezone.utc),
            size=100,
            version=1,
            is_deleted=False,
        )
        index.update_entry("conversation.json", metadata)

        # Save
        index.save()
        assert index_file.exists()

        # Load in new index
        new_index = HistoryLocalIndex(index_file)
        entries = new_index.load()

        assert "conversation.json" in entries
        assert entries["conversation.json"].md5 == "test_md5"
        assert entries["conversation.json"].version == 1


class TestHistorySyncEngine:
    """Tests for HistorySyncEngine."""

    def test_init(self, mock_client, session_dir):
        """Test engine initialization."""
        config = SyncConfig.for_history("test", "session-1")
        engine = HistorySyncEngine(client=mock_client, config=config)

        assert engine.client == mock_client
        assert engine.config == config
        assert engine.compression_level == 6
        assert engine._session_dir == session_dir

    def test_scan_local_files(self, mock_client, session_dir):
        """Test scanning local session files."""
        config = SyncConfig.for_history("test", "session-1")
        engine = HistorySyncEngine(client=mock_client, config=config)

        files = engine._scan_local_files()

        assert "conversation.json" in files
        assert "conversation-1.json" in files
        assert files["conversation.json"]["size"] > 0
        assert files["conversation.json"]["md5"] is not None

    def test_push_file_compresses_content(self, mock_client, session_dir):
        """Test that push_file compresses content with gzip."""
        config = SyncConfig.for_history("test", "session-1")
        engine = HistorySyncEngine(client=mock_client, config=config)

        # Mock write_blob
        mock_client.write_blob.return_value = (True, "test_md5", 1)

        # Create file info
        file_path = "conversation.json"
        content = b'{"messages": []}'
        file_info = {
            "md5": "test_md5",
            "size": len(content),
            "mtime": 123456,
        }

        # Push file
        compressed_size = engine._push_file(file_path, file_info, None)

        # Verify write_blob was called with compressed content
        mock_client.write_blob.assert_called_once()
        call_args = mock_client.write_blob.call_args

        # Check that content is compressed
        uploaded_content = call_args.kwargs["content"]
        assert uploaded_content != content  # Should be compressed

        # Decompress and verify
        decompressed = gzip.decompress(uploaded_content)
        assert decompressed == content

        # Check path has .gz extension
        assert call_args.kwargs["path"] == "conversation.json.gz"

        # Check content type
        assert call_args.kwargs["content_type"] == "application/gzip"

        # Check compressed size is returned
        assert compressed_size == len(uploaded_content)

    def test_push_all_compresses_all_files(self, mock_client, session_dir):
        """Test that push_all compresses all files."""
        config = SyncConfig.for_history("test", "session-1")
        engine = HistorySyncEngine(client=mock_client, config=config)

        # Create a larger file that will actually compress well
        large_content = '{"messages": [' + ', '.join(['"msg"'] * 100) + ']}'
        (session_dir / "large.json").write_text(large_content)

        # Mock write_blob
        mock_client.write_blob.return_value = (True, "test_md5", 1)

        # Push all files
        result = engine.push_all(show_progress=False)

        # Should have pushed 3 files (including the large one)
        assert len(result.succeeded) == 3
        assert "conversation.json" in result.succeeded
        assert "conversation-1.json" in result.succeeded
        assert "large.json" in result.succeeded

        # Should have compression stats for large file
        assert "large.json" in result.compressed_sizes
        original, compressed = result.compressed_sizes["large.json"]
        # Large file should compress well
        assert compressed < original
        assert compressed / original < 0.5  # Should be less than 50% of original

    def test_push_all_skips_already_pushed(self, mock_client, session_dir):
        """Test that push_all skips files already pushed."""
        config = SyncConfig.for_history("test", "session-1")
        engine = HistorySyncEngine(client=mock_client, config=config)

        # Mock write_blob
        mock_client.write_blob.return_value = (True, "test_md5", 1)

        # First push
        result1 = engine.push_all(show_progress=False)
        assert len(result1.succeeded) == 2

        # Second push (nothing changed)
        result2 = engine.push_all(show_progress=False)

        # Should still succeed but not call write_blob again
        assert len(result2.succeeded) == 2
        # write_blob should only be called twice (from first push)
        assert mock_client.write_blob.call_count == 2

    def test_pull_file_decompresses_content(self, mock_client, session_dir):
        """Test that pull_file decompresses content."""
        config = SyncConfig.for_history("test", "session-1")
        engine = HistorySyncEngine(client=mock_client, config=config)

        # Create compressed content
        original_content = b'{"messages": ["test"]}'
        compressed_content = gzip.compress(original_content)

        # Mock read_blob
        mock_client.read_blob.return_value = (
            compressed_content,
            "test_md5",
            datetime.now(timezone.utc),
            "application/gzip",
            1,
        )

        # Pull file
        local_path = engine._pull_file("conversation.json.gz")

        # Verify file was created and decompressed
        assert local_path.exists()
        with open(local_path, "rb") as f:
            content = f.read()
        assert content == original_content

        # Verify .gz extension was removed
        assert local_path.name == "conversation.json"

    def test_pull_session_downloads_all_files(self, mock_client, session_dir):
        """Test that pull_session downloads all session files."""
        config = SyncConfig.for_history("test", "session-1")
        engine = HistorySyncEngine(client=mock_client, config=config)

        # Mock remote index with 2 files
        remote_files = {
            "conversation.json.gz": FileMetadata(
                md5="md5_1",
                last_modified=datetime.now(timezone.utc),
                size=100,
                version=1,
                is_deleted=False,
            ),
            "conversation-1.json.gz": FileMetadata(
                md5="md5_2",
                last_modified=datetime.now(timezone.utc),
                size=200,
                version=1,
                is_deleted=False,
            ),
        }

        mock_client.get_sync_index.return_value = SyncIndexResponse(
            files=remote_files,
            index_last_modified=datetime.now(timezone.utc),
            index_version=1,
        )

        # Mock read_blob
        def mock_read_blob(namespace, path):
            content = b'{"messages": []}'
            compressed = gzip.compress(content)
            return (
                compressed,
                "test_md5",
                datetime.now(timezone.utc),
                "application/gzip",
                1,
            )

        mock_client.read_blob.side_effect = mock_read_blob

        # Pull session
        pulled = engine.pull_session(show_progress=False)

        # Should have pulled 2 files
        assert len(pulled) == 2
        assert "conversation.json.gz" in pulled
        assert "conversation-1.json.gz" in pulled

        # Files should exist locally
        assert (session_dir / "conversation.json").exists()
        assert (session_dir / "conversation-1.json").exists()

    def test_compression_ratio_calculation(self):
        """Test compression ratio calculation."""
        result = HistoryPushResult(
            succeeded=["test.json"],
            failed=[],
            compressed_sizes={
                "test.json": (1000, 300),  # 30% of original
            },
        )

        ratio = result.compression_ratio("test.json")
        assert ratio == 0.3

    def test_compression_level_configurable(self, mock_client, session_dir):
        """Test that compression level is configurable."""
        config = SyncConfig.for_history("test", "session-1")

        # Create engine with different compression levels
        engine_fast = HistorySyncEngine(
            client=mock_client, config=config, compression_level=1
        )
        engine_best = HistorySyncEngine(
            client=mock_client, config=config, compression_level=9
        )

        assert engine_fast.compression_level == 1
        assert engine_best.compression_level == 9


class TestHistorySyncIntegration:
    """Integration tests for history sync."""

    def test_push_and_pull_roundtrip(self, mock_client, session_dir):
        """Test that pushing and pulling results in identical content."""
        config = SyncConfig.for_history("test", "session-1")
        engine = HistorySyncEngine(client=mock_client, config=config)

        # Storage for uploaded files
        uploaded_files = {}

        # Mock write_blob to store files
        def mock_write_blob(namespace, path, content, expected_version, content_type):
            uploaded_files[path] = content
            return (True, "test_md5", 1)

        mock_client.write_blob.side_effect = mock_write_blob

        # Push files
        push_result = engine.push_all(show_progress=False)
        assert len(push_result.succeeded) == 2

        # Verify files are compressed
        assert "conversation.json.gz" in uploaded_files
        compressed_content = uploaded_files["conversation.json.gz"]

        # Mock read_blob to return stored files
        def mock_read_blob(namespace, path):
            if path in uploaded_files:
                return (
                    uploaded_files[path],
                    "test_md5",
                    datetime.now(timezone.utc),
                    "application/gzip",
                    1,
                )
            raise KeyError(f"File not found: {path}")

        mock_client.read_blob.side_effect = mock_read_blob

        # Mock get_sync_index to return uploaded files
        remote_files = {
            path: FileMetadata(
                md5="test_md5",
                last_modified=datetime.now(timezone.utc),
                size=len(content),
                version=1,
                is_deleted=False,
            )
            for path, content in uploaded_files.items()
        }

        mock_client.get_sync_index.return_value = SyncIndexResponse(
            files=remote_files,
            index_last_modified=datetime.now(timezone.utc),
            index_version=1,
        )

        # Clear local session directory
        for f in session_dir.glob("*.json"):
            f.unlink()

        # Pull files
        pulled = engine.pull_session(show_progress=False)
        assert len(pulled) == 2

        # Verify content is identical
        assert (session_dir / "conversation.json").exists()
        with open(session_dir / "conversation.json", "r") as f:
            content = f.read()
        assert content == '{"messages": []}'
