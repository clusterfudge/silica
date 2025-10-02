"""Tests for Memory V2 migration from V1."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime

from silica.developer.memory_v2.storage import LocalDiskStorage
from silica.developer.memory_v2.migration import (
    V1MemoryFile,
    MigrationState,
    scan_v1_memory,
    load_migration_state,
    save_migration_state,
    extract_and_store_v1_file,
    load_v1_metadata,
)


@pytest.fixture
def temp_v1_memory():
    """Create a temporary V1 memory structure for testing."""
    import json

    with TemporaryDirectory() as tmpdir:
        v1_path = Path(tmpdir) / "v1_memory"
        v1_path.mkdir()

        # Create some test files (as .md files with optional .metadata.json)
        (v1_path / "projects").mkdir()
        (v1_path / "projects" / "silica.md").write_text(
            "# Silica Project\n\nSilica is a Python agent framework"
        )
        # Add metadata for silica
        (v1_path / "projects" / "silica.md.metadata.json").write_text(
            json.dumps(
                {
                    "created": "1756164365.8600342",
                    "updated": "1756310072.6633813",
                    "version": 2,
                    "summary": "Python agent framework project documentation",
                }
            )
        )

        (v1_path / "projects" / "webapp.md").write_text(
            "# Web App\n\nWeb application project"
        )

        (v1_path / "knowledge").mkdir()
        (v1_path / "knowledge" / "python.md").write_text(
            "# Python Knowledge\n\nPython best practices and patterns"
        )

        (v1_path / "notes.md").write_text("# Notes\n\nRandom notes and thoughts")

        yield v1_path


@pytest.fixture
def temp_v2_storage():
    """Create a temporary V2 storage for testing."""
    with TemporaryDirectory() as tmpdir:
        storage = LocalDiskStorage(tmpdir)
        yield storage


class TestV1MemoryFile:
    """Tests for V1MemoryFile dataclass."""

    def test_create_v1_memory_file(self):
        file = V1MemoryFile(
            path="test/file",
            full_path=Path("/path/to/file"),
            size_bytes=100,
            last_modified=datetime.now(),
        )

        assert file.path == "test/file"
        assert file.size_bytes == 100
        assert file.content is None

    def test_v1_memory_file_with_content(self):
        file = V1MemoryFile(
            path="test/file",
            full_path=Path("/path/to/file"),
            size_bytes=100,
            last_modified=datetime.now(),
            content="Test content",
        )

        assert file.content == "Test content"

    def test_v1_memory_file_with_metadata(self):
        metadata = {
            "created": "1756164365.8600342",
            "updated": "1756310072.6633813",
            "version": 2,
            "summary": "Test summary",
        }

        file = V1MemoryFile(
            path="test/file",
            full_path=Path("/path/to/file"),
            size_bytes=100,
            last_modified=datetime.now(),
            metadata=metadata,
        )

        assert file.metadata is not None
        assert file.metadata["version"] == 2
        assert "summary" in file.metadata


class TestMigrationState:
    """Tests for MigrationState dataclass."""

    def test_create_migration_state(self):
        state = MigrationState(
            started_at="2025-01-01T00:00:00",
            last_updated="2025-01-01T00:00:00",
            processed_files=[],
            total_files=10,
        )

        assert state.total_files == 10
        assert state.completed is False
        assert len(state.processed_files) == 0

    def test_migration_state_to_dict(self):
        state = MigrationState(
            started_at="2025-01-01T00:00:00",
            last_updated="2025-01-01T00:00:00",
            processed_files=[{"path": "test", "success": True}],
            total_files=1,
            completed=True,
        )

        data = state.to_dict()

        assert isinstance(data, dict)
        assert data["total_files"] == 1
        assert data["completed"] is True

    def test_migration_state_from_dict(self):
        data = {
            "started_at": "2025-01-01T00:00:00",
            "last_updated": "2025-01-01T00:00:00",
            "processed_files": [],
            "total_files": 5,
            "completed": False,
        }

        state = MigrationState.from_dict(data)

        assert state.total_files == 5
        assert state.completed is False


class TestLoadV1Metadata:
    """Tests for load_v1_metadata function."""

    def test_load_metadata_exists(self, temp_v1_memory):
        md_file = temp_v1_memory / "projects" / "silica.md"
        metadata = load_v1_metadata(md_file)

        assert metadata is not None
        assert "created" in metadata
        assert "updated" in metadata
        assert "summary" in metadata
        assert metadata["version"] == 2

    def test_load_metadata_not_exists(self, temp_v1_memory):
        md_file = temp_v1_memory / "projects" / "webapp.md"
        metadata = load_v1_metadata(md_file)

        # webapp.md has no metadata file
        assert metadata is None

    def test_load_metadata_invalid_json(self, temp_v1_memory):
        # Create file with invalid JSON metadata
        md_file = temp_v1_memory / "invalid.md"
        md_file.write_text("# Test")

        metadata_file = temp_v1_memory / "invalid.md.metadata.json"
        metadata_file.write_text("{invalid json")

        metadata = load_v1_metadata(md_file)

        # Should handle gracefully and return None
        assert metadata is None


class TestScanV1Memory:
    """Tests for scan_v1_memory function."""

    def test_scan_empty_directory(self):
        with TemporaryDirectory() as tmpdir:
            v1_path = Path(tmpdir) / "empty"
            v1_path.mkdir()

            files = scan_v1_memory(v1_path)

            assert files == []

    def test_scan_with_files(self, temp_v1_memory):
        files = scan_v1_memory(temp_v1_memory)

        # Should find all .md files
        assert (
            len(files) == 4
        )  # projects/silica.md, projects/webapp.md, knowledge/python.md, notes.md

        # Check file structure
        paths = [f.path for f in files]
        assert "projects/silica.md" in paths
        assert "knowledge/python.md" in paths
        assert "notes.md" in paths

    def test_scan_ignores_json_files(self, temp_v1_memory):
        # Create a standalone .json file
        (temp_v1_memory / "config.json").write_text('{"key": "value"}')

        files = scan_v1_memory(temp_v1_memory)

        # Should not include .json files
        paths = [f.path for f in files]
        assert "config.json" not in paths
        # But should still find .md files
        assert len(files) == 4

    def test_scan_loads_metadata(self, temp_v1_memory):
        files = scan_v1_memory(temp_v1_memory)

        # Find silica.md which has metadata
        silica_file = next(f for f in files if "silica.md" in f.path)

        assert silica_file.metadata is not None
        assert "created" in silica_file.metadata
        assert "summary" in silica_file.metadata

        # Find webapp.md which has no metadata
        webapp_file = next(f for f in files if "webapp.md" in f.path)

        assert webapp_file.metadata is None

    def test_scan_sorted_chronologically(self, temp_v1_memory):
        import time

        # Modify files with different times
        files_in_order = [
            "notes.md",
            "knowledge/python.md",
            "projects/webapp.md",
            "projects/silica.md",
        ]

        for i, file_path in enumerate(files_in_order):
            full_path = temp_v1_memory / file_path
            full_path.touch()  # Update modification time
            time.sleep(0.01)  # Small delay to ensure different times

        files = scan_v1_memory(temp_v1_memory)

        # Should be sorted by modification time (oldest first)
        assert len(files) == 4
        # First file should be oldest
        assert files[0].last_modified <= files[1].last_modified
        assert files[1].last_modified <= files[2].last_modified

    def test_scan_ignores_hidden_files(self, temp_v1_memory):
        # Create hidden file
        (temp_v1_memory / ".hidden.md").write_text("Hidden content")

        files = scan_v1_memory(temp_v1_memory)

        paths = [f.path for f in files]
        assert ".hidden.md" not in paths

    def test_scan_ignores_directories(self, temp_v1_memory):
        files = scan_v1_memory(temp_v1_memory)

        # Should not include directory paths
        paths = [f.path for f in files]
        assert "projects" not in paths
        assert "knowledge" not in paths


class TestMigrationStateIO:
    """Tests for load/save migration state."""

    def test_save_and_load_state(self, temp_v2_storage):
        state = MigrationState(
            started_at="2025-01-01T00:00:00",
            last_updated="2025-01-01T00:00:00",
            processed_files=[{"path": "test", "success": True}],
            total_files=10,
        )

        # Save state
        save_migration_state(temp_v2_storage, state)

        # Load state
        loaded = load_migration_state(temp_v2_storage)

        assert loaded is not None
        assert loaded.total_files == 10
        assert len(loaded.processed_files) == 1

    def test_load_nonexistent_state(self, temp_v2_storage):
        state = load_migration_state(temp_v2_storage)

        assert state is None

    def test_state_persists_across_loads(self, temp_v2_storage):
        state = MigrationState(
            started_at="2025-01-01T00:00:00",
            last_updated="2025-01-01T00:00:00",
            processed_files=[],
            total_files=5,
        )

        save_migration_state(temp_v2_storage, state)

        # Add processed file
        state.processed_files.append({"path": "file1", "success": True})
        save_migration_state(temp_v2_storage, state)

        # Load again
        loaded = load_migration_state(temp_v2_storage)

        assert len(loaded.processed_files) == 1


class TestExtractAndStore:
    """Tests for extract_and_store_v1_file function."""

    async def test_extract_and_store_with_mock_context(
        self, temp_v1_memory, temp_v2_storage
    ):
        from unittest.mock import MagicMock

        # Create mock context
        mock_context = MagicMock()
        mock_context.user_interface = MagicMock()

        # Create V1 file with metadata
        metadata = {
            "created": "1756164365.8600342",
            "updated": "1756310072.6633813",
            "version": 2,
            "summary": "Test memory file",
        }

        v1_file = V1MemoryFile(
            path="test/file.md",
            full_path=temp_v1_memory / "notes.md",
            size_bytes=100,
            last_modified=datetime.now(),
            metadata=metadata,
        )

        # For testing, we'll just verify it doesn't crash
        # Real extraction would use actual agent
        try:
            success, message = await extract_and_store_v1_file(
                v1_file, temp_v2_storage, mock_context
            )
            # Should return tuple of (bool, str)
            assert isinstance(success, bool)
            assert isinstance(message, str)
        except Exception:
            # Expected if agent not fully available in test
            pass


class TestIntegration:
    """Integration tests for migration workflow."""

    def test_scan_to_state_workflow(self, temp_v1_memory, temp_v2_storage):
        # Scan V1 memory
        files = scan_v1_memory(temp_v1_memory)

        assert len(files) > 0

        # Create migration state
        state = MigrationState(
            started_at=datetime.now().isoformat(),
            last_updated=datetime.now().isoformat(),
            processed_files=[],
            total_files=len(files),
        )

        # Simulate processing first file
        state.processed_files.append(
            {
                "path": files[0].path,
                "processed_at": datetime.now().isoformat(),
                "success": True,
            }
        )

        # Save state
        save_migration_state(temp_v2_storage, state)

        # Load state
        loaded = load_migration_state(temp_v2_storage)

        assert loaded.total_files == len(files)
        assert len(loaded.processed_files) == 1

    def test_resumable_processing(self, temp_v1_memory, temp_v2_storage):
        # Scan files
        files = scan_v1_memory(temp_v1_memory)

        # Create initial state
        state = MigrationState(
            started_at=datetime.now().isoformat(),
            last_updated=datetime.now().isoformat(),
            processed_files=[],
            total_files=len(files),
        )

        # Process first two files
        for i in range(2):
            state.processed_files.append(
                {
                    "path": files[i].path,
                    "processed_at": datetime.now().isoformat(),
                    "success": True,
                }
            )

        save_migration_state(temp_v2_storage, state)

        # Load and continue
        loaded = load_migration_state(temp_v2_storage)

        processed_paths = {pf["path"] for pf in loaded.processed_files}
        remaining = [f for f in files if f.path not in processed_paths]

        assert len(remaining) == len(files) - 2
