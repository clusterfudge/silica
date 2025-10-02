"""
Tests for Memory V2 storage layer.
"""

import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest

from silica.developer.memory_v2 import LocalDiskStorage
from silica.developer.memory_v2.exceptions import (
    MemoryNotFoundError,
    MemoryInvalidPathError,
)


@pytest.fixture
def temp_storage():
    """Create a temporary storage instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalDiskStorage(tmpdir)
        yield storage


class TestPersonaRoot:
    """Tests for persona root (empty path) handling."""

    def test_write_and_read_persona_root(self, temp_storage):
        """Test writing and reading from persona root (empty path)."""
        # Write to root
        temp_storage.write("", "Root content for this persona")

        # Read from root
        content = temp_storage.read("")
        assert content == "Root content for this persona"

    def test_persona_root_path_validation(self, temp_storage):
        """Test that empty path is valid and maps to base_path."""
        # Empty path should be valid
        assert temp_storage.exists("") is False  # Not created yet

        # Write and verify it exists
        temp_storage.write("", "Content")
        assert temp_storage.exists("")

    def test_persona_root_with_children(self, temp_storage):
        """Test that persona root can have both content and children."""
        # Write to root
        temp_storage.write("", "Root overview")

        # Write children
        temp_storage.write("projects", "Projects content")
        temp_storage.write("knowledge", "Knowledge content")

        # All should coexist
        assert temp_storage.exists("")
        assert temp_storage.exists("projects")
        assert temp_storage.exists("knowledge")

        # Should be able to read all
        assert "Root overview" in temp_storage.read("")
        assert "Projects content" in temp_storage.read("projects")
        assert "Knowledge content" in temp_storage.read("knowledge")

    def test_list_files_includes_root(self, temp_storage):
        """Test that list_files includes the root if it has content."""
        # Write to root and some children
        temp_storage.write("", "Root content")
        temp_storage.write("projects", "Projects")

        files = temp_storage.list_files()

        # Should include both root (as "") and children
        assert "" in files  # Root represented as empty string
        assert "projects" in files
        assert len(files) == 2

    def test_persona_root_size_and_metadata(self, temp_storage):
        """Test getting size and metadata for persona root."""
        content = "Root content for testing"
        temp_storage.write("", content)

        # Should be able to get size
        size = temp_storage.get_size("")
        assert size == len(content)

        # Should be able to get modified time
        modified = temp_storage.get_modified_time("")
        assert modified is not None


class TestLocalDiskStorage:
    """Tests for LocalDiskStorage implementation."""

    def test_init_creates_directories(self):
        """Test that initialization creates necessary directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "memory_test"
            storage = LocalDiskStorage(base_path)

            assert storage.base_path.exists()
            assert storage.base_path.is_dir()
            assert storage.metadata_path.exists()
            assert storage.metadata_path.is_dir()

    def test_init_with_default_path(self):
        """Test initialization with default path."""
        storage = LocalDiskStorage()
        expected_path = Path.home() / ".silica" / "memory_v2"
        assert storage.base_path == expected_path

    def test_write_and_read(self, temp_storage):
        """Test basic write and read operations."""
        content = "Test memory content"
        temp_storage.write("memory", content)

        assert temp_storage.exists("memory")
        assert temp_storage.read("memory") == content

    def test_write_creates_parent_directories(self, temp_storage):
        """Test that write creates parent directories."""
        content = "Nested content"
        temp_storage.write("projects/silica/architecture", content)

        assert temp_storage.exists("projects/silica/architecture")
        assert temp_storage.read("projects/silica/architecture") == content

    def test_write_overwrites_existing(self, temp_storage):
        """Test that write overwrites existing content."""
        temp_storage.write("memory", "Original content")
        temp_storage.write("memory", "Updated content")

        assert temp_storage.read("memory") == "Updated content"

    def test_read_nonexistent_raises_error(self, temp_storage):
        """Test that reading nonexistent file raises MemoryNotFoundError."""
        with pytest.raises(MemoryNotFoundError):
            temp_storage.read("nonexistent")

    def test_exists_returns_false_for_nonexistent(self, temp_storage):
        """Test that exists returns False for nonexistent files."""
        assert not temp_storage.exists("nonexistent")

    def test_exists_returns_true_for_existing(self, temp_storage):
        """Test that exists returns True for existing files."""
        temp_storage.write("memory", "content")
        assert temp_storage.exists("memory")

    def test_list_files_empty(self, temp_storage):
        """Test listing files when storage is empty."""
        assert temp_storage.list_files() == []

    def test_list_files_with_content(self, temp_storage):
        """Test listing files with content."""
        temp_storage.write("memory", "root")
        temp_storage.write("knowledge", "knowledge content")
        temp_storage.write("projects/silica", "silica content")
        temp_storage.write("projects/personal", "personal content")

        files = temp_storage.list_files()
        assert set(files) == {
            "memory",
            "knowledge",
            "projects/silica",
            "projects/personal",
        }

    def test_list_files_excludes_metadata(self, temp_storage):
        """Test that list_files excludes metadata directory."""
        temp_storage.write("memory", "content")

        # Write to metadata dir
        metadata_file = temp_storage.metadata_path / "graph.json"
        metadata_file.write_text('{"test": true}')

        files = temp_storage.list_files()
        assert files == ["memory"]
        assert not any(".metadata" in f for f in files)

    def test_delete(self, temp_storage):
        """Test deleting files."""
        temp_storage.write("memory", "content")
        assert temp_storage.exists("memory")

        temp_storage.delete("memory")
        assert not temp_storage.exists("memory")

    def test_delete_nonexistent_raises_error(self, temp_storage):
        """Test that deleting nonexistent file raises error."""
        with pytest.raises(MemoryNotFoundError):
            temp_storage.delete("nonexistent")

    def test_get_size(self, temp_storage):
        """Test getting file size."""
        content = "Test content"
        temp_storage.write("memory", content)

        size = temp_storage.get_size("memory")
        assert size == len(content.encode("utf-8"))

    def test_get_size_nonexistent_raises_error(self, temp_storage):
        """Test that getting size of nonexistent file raises error."""
        with pytest.raises(MemoryNotFoundError):
            temp_storage.get_size("nonexistent")

    def test_get_modified_time(self, temp_storage):
        """Test getting modified time."""
        before = datetime.now()
        temp_storage.write("memory", "content")
        after = datetime.now()

        modified = temp_storage.get_modified_time("memory")
        assert before <= modified <= after

    def test_get_modified_time_updates(self, temp_storage):
        """Test that modified time updates on write."""
        temp_storage.write("memory", "original")
        time1 = temp_storage.get_modified_time("memory")

        time.sleep(0.01)  # Ensure time difference

        temp_storage.write("memory", "updated")
        time2 = temp_storage.get_modified_time("memory")

        assert time2 > time1

    def test_get_modified_time_nonexistent_raises_error(self, temp_storage):
        """Test that getting modified time of nonexistent file raises error."""
        with pytest.raises(MemoryNotFoundError):
            temp_storage.get_modified_time("nonexistent")

    def test_path_validation_empty_path(self, temp_storage):
        """Test that empty path is valid (maps to persona root)."""
        # Empty path should be valid now - it means the root
        # Initially doesn't exist
        assert not temp_storage.exists("")

        # Can write to it
        temp_storage.write("", "Root content")

        # Now exists and can be read
        assert temp_storage.exists("")
        assert temp_storage.read("") == "Root content"

    def test_path_validation_absolute_path(self, temp_storage):
        """Test that absolute paths are rejected."""
        with pytest.raises(MemoryInvalidPathError):
            temp_storage.read("/etc/passwd")

    def test_path_validation_parent_traversal(self, temp_storage):
        """Test that parent directory traversal is rejected."""
        with pytest.raises(MemoryInvalidPathError):
            temp_storage.read("../../../etc/passwd")

    def test_path_validation_escaping_base(self, temp_storage):
        """Test that paths escaping base directory are rejected."""
        with pytest.raises(MemoryInvalidPathError):
            temp_storage.read("projects/../../../etc/passwd")

    def test_unicode_content(self, temp_storage):
        """Test writing and reading Unicode content."""
        content = "Hello 世界 🌍 Привет"
        temp_storage.write("memory", content)

        assert temp_storage.read("memory") == content

    def test_large_content(self, temp_storage):
        """Test writing and reading large content."""
        # Create 1MB of content
        content = "x" * (1024 * 1024)
        temp_storage.write("memory", content)

        assert temp_storage.read("memory") == content
        assert temp_storage.get_size("memory") == 1024 * 1024

    def test_path_normalization(self, temp_storage):
        """Test that paths with different separators work."""
        temp_storage.write("projects/silica", "content")

        # Both should work
        assert temp_storage.exists("projects/silica")

        # List should use forward slashes
        files = temp_storage.list_files()
        assert "projects/silica" in files

    def test_atomic_write(self, temp_storage):
        """Test that writes are atomic (no partial writes visible)."""
        # This is a basic test - in practice we'd need concurrent access
        # to truly test atomicity
        content = "A" * 10000
        temp_storage.write("memory", content)

        # File should either exist with full content or not exist
        if temp_storage.exists("memory"):
            assert temp_storage.read("memory") == content

    def test_concurrent_reads(self, temp_storage):
        """Test that multiple readers can access the same file."""
        content = "Shared content"
        temp_storage.write("memory", content)

        # Simulate multiple concurrent reads
        results = []
        for _ in range(5):
            results.append(temp_storage.read("memory"))

        assert all(r == content for r in results)

    def test_file_locking_prevents_corruption(self, temp_storage):
        """Test that file locking helps prevent corruption."""
        # This is a basic test - true concurrent testing would require
        # multiprocessing or threading
        temp_storage.write("memory", "initial")

        # Subsequent writes should complete successfully
        for i in range(10):
            temp_storage.write("memory", f"update {i}")

        # Final content should be consistent
        content = temp_storage.read("memory")
        assert content.startswith("update")

    def test_empty_content(self, temp_storage):
        """Test writing and reading empty content."""
        temp_storage.write("memory", "")

        assert temp_storage.exists("memory")
        assert temp_storage.read("memory") == ""
        assert temp_storage.get_size("memory") == 0

    def test_special_characters_in_path(self, temp_storage):
        """Test paths with special characters."""
        # Allowed special characters
        paths = [
            "memory-file",
            "memory_file",
            "memory.file",
            "projects/my-project",
            "knowledge/python_3.11",
        ]

        for path in paths:
            temp_storage.write(path, "content")
            assert temp_storage.exists(path)
            assert temp_storage.read(path) == "content"

    def test_nested_directories(self, temp_storage):
        """Test deeply nested directory structures."""
        path = "a/b/c/d/e/f/memory"
        temp_storage.write(path, "deep content")

        assert temp_storage.exists(path)
        assert temp_storage.read(path) == "deep content"

    def test_list_files_sorted(self, temp_storage):
        """Test that list_files returns sorted results."""
        paths = ["zebra", "alpha", "beta", "gamma"]
        for path in paths:
            temp_storage.write(path, "content")

        files = temp_storage.list_files()
        assert files == sorted(paths)

    def test_parent_and_child_nodes(self, temp_storage):
        """Test that we can have both a parent node and child nodes."""
        # Create a parent node
        temp_storage.write("projects", "Overview of all projects")
        assert temp_storage.exists("projects")
        assert temp_storage.read("projects") == "Overview of all projects"

        # Create child nodes - this should work!
        temp_storage.write("projects/silica", "Silica project details")
        temp_storage.write("projects/personal", "Personal project details")

        # All should exist and be readable
        assert temp_storage.exists("projects")
        assert temp_storage.exists("projects/silica")
        assert temp_storage.exists("projects/personal")

        assert temp_storage.read("projects") == "Overview of all projects"
        assert temp_storage.read("projects/silica") == "Silica project details"
        assert temp_storage.read("projects/personal") == "Personal project details"

        # List should show all nodes
        files = temp_storage.list_files()
        assert set(files) == {"projects", "projects/silica", "projects/personal"}

    def test_node_transforms_from_leaf_to_parent(self, temp_storage):
        """Test organic growth: a leaf node becomes a parent."""
        # Start as a leaf node
        temp_storage.write("memory", "Initial thoughts")
        assert temp_storage.read("memory") == "Initial thoughts"

        # Update the content
        temp_storage.write("memory", "Updated with more context")
        assert temp_storage.read("memory") == "Updated with more context"

        # Now it grows children (organic split)
        temp_storage.write("memory/projects", "Project information")
        temp_storage.write("memory/knowledge", "Technical knowledge")

        # Parent still exists and is readable
        assert temp_storage.read("memory") == "Updated with more context"

        # Children exist and are readable
        assert temp_storage.read("memory/projects") == "Project information"
        assert temp_storage.read("memory/knowledge") == "Technical knowledge"

        # All show up in list
        files = temp_storage.list_files()
        assert set(files) == {"memory", "memory/projects", "memory/knowledge"}
