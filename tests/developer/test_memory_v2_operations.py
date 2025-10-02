"""Tests for Memory V2 operations (agentic features)."""

import pytest
from tempfile import TemporaryDirectory

from silica.developer.memory_v2.storage import LocalDiskStorage
from silica.developer.memory_v2.operations import (
    WriteResult,
    SearchResult,
    agentic_write,
    extract_links,
    search_memory,
    split_memory_node,
    SIZE_THRESHOLD,
)


@pytest.fixture
def temp_storage():
    """Create a temporary storage for testing."""
    with TemporaryDirectory() as tmpdir:
        storage = LocalDiskStorage(tmpdir)
        yield storage


class TestWriteResult:
    """Tests for WriteResult dataclass."""

    def test_basic_write_result(self):
        result = WriteResult(
            success=True, path="memory", size_bytes=1024, split_triggered=False
        )

        assert result.success is True
        assert result.path == "memory"
        assert result.size_bytes == 1024
        assert result.split_triggered is False
        assert result.new_files == []

    def test_write_result_with_split(self):
        result = WriteResult(
            success=True,
            path="memory",
            size_bytes=12000,
            split_triggered=True,
            new_files=["projects", "knowledge"],
        )

        assert result.split_triggered is True
        assert len(result.new_files) == 2
        assert "projects" in result.new_files

    def test_write_result_new_files_default(self):
        result = WriteResult(success=True, path="test", size_bytes=100)
        assert result.new_files == []


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_basic_search_result(self):
        result = SearchResult(
            path="memory",
            excerpt="Test excerpt",
            relevance_score=0.8,
            context="Test context",
        )

        assert result.path == "memory"
        assert result.excerpt == "Test excerpt"
        assert result.relevance_score == 0.8
        assert result.context == "Test context"

    def test_search_result_default_context(self):
        result = SearchResult(path="test", excerpt="excerpt", relevance_score=0.5)
        assert result.context == ""


class TestExtractLinks:
    """Tests for extract_links function."""

    def test_extract_single_link(self):
        content = "See [[projects]] for more info"
        links = extract_links(content)
        assert links == ["projects"]

    def test_extract_multiple_links(self):
        content = """
        See [[projects]] and [[knowledge]] for details.
        Also check [[notes/meeting]].
        """
        links = extract_links(content)
        assert len(links) == 3
        assert "projects" in links
        assert "knowledge" in links
        assert "notes/meeting" in links

    def test_extract_no_links(self):
        content = "This has no links at all"
        links = extract_links(content)
        assert links == []

    def test_extract_nested_path_links(self):
        content = "Check [[projects/silica]] for details"
        links = extract_links(content)
        assert links == ["projects/silica"]

    def test_extract_ignores_malformed_links(self):
        content = "This has [single brackets] and [[valid]] link"
        links = extract_links(content)
        assert links == ["valid"]


class TestAgenticWrite:
    """Tests for agentic_write function."""

    def test_write_new_file(self, temp_storage):
        """Test writing to a new file."""
        result = agentic_write(temp_storage, "memory", "Initial content")

        assert result.success is True
        assert result.path == "memory"
        assert result.size_bytes > 0
        assert result.split_triggered is False

        # Verify content was written
        content = temp_storage.read("memory")
        assert "Initial content" in content

    def test_write_merge_existing(self, temp_storage):
        """Test merging with existing content."""
        # Write initial content
        temp_storage.write("memory", "Old information")

        # Write new content (should merge)
        result = agentic_write(temp_storage, "memory", "New information")

        assert result.success is True
        content = temp_storage.read("memory")

        # Both old and new should be present
        assert "Old information" in content
        assert "New information" in content

    def test_write_triggers_split_flag(self, temp_storage):
        """Test that large files trigger split flag."""
        # Create content over threshold
        large_content = "x" * (SIZE_THRESHOLD + 100)
        result = agentic_write(temp_storage, "memory", large_content)

        assert result.success is True
        assert result.split_triggered is True
        assert result.size_bytes > SIZE_THRESHOLD

    def test_write_no_split_flag_below_threshold(self, temp_storage):
        """Test that small files don't trigger split flag."""
        result = agentic_write(temp_storage, "memory", "Small content")

        assert result.success is True
        assert result.split_triggered is False
        assert result.size_bytes < SIZE_THRESHOLD

    def test_write_nested_path(self, temp_storage):
        """Test writing to nested path."""
        result = agentic_write(temp_storage, "projects/silica", "Silica project info")

        assert result.success is True
        assert result.path == "projects/silica"

        # Verify content
        content = temp_storage.read("projects/silica")
        assert "Silica project info" in content


class TestSearchMemory:
    """Tests for search_memory function."""

    def test_search_single_file(self, temp_storage):
        """Test searching with one matching file."""
        temp_storage.write("memory", "This is about Python programming")

        results = search_memory(temp_storage, "Python")

        assert len(results) == 1
        assert results[0].path == "memory"
        assert "Python" in results[0].excerpt
        assert results[0].relevance_score > 0

    def test_search_multiple_files(self, temp_storage):
        """Test searching across multiple files."""
        temp_storage.write("memory", "Python is great")
        temp_storage.write("projects", "Python project details")
        temp_storage.write("knowledge", "Python best practices")

        results = search_memory(temp_storage, "Python", max_results=5)

        assert len(results) == 3
        # All should have Python in them
        for result in results:
            assert "Python" in result.excerpt or "Python" in temp_storage.read(
                result.path
            )

    def test_search_no_matches(self, temp_storage):
        """Test searching with no matches."""
        temp_storage.write("memory", "This is about JavaScript")

        results = search_memory(temp_storage, "Python")

        assert len(results) == 0

    def test_search_respects_max_results(self, temp_storage):
        """Test that max_results is respected."""
        # Create many files with the search term
        for i in range(10):
            temp_storage.write(f"file{i}", f"Python content {i}")

        results = search_memory(temp_storage, "Python", max_results=5)

        assert len(results) <= 5

    def test_search_case_insensitive(self, temp_storage):
        """Test that search is case-insensitive."""
        temp_storage.write("memory", "This is about PYTHON programming")

        results = search_memory(temp_storage, "python")

        assert len(results) == 1
        assert results[0].path == "memory"

    def test_search_returns_excerpt(self, temp_storage):
        """Test that results include excerpts."""
        content = "x" * 100 + "Python programming" + "y" * 100
        temp_storage.write("memory", content)

        results = search_memory(temp_storage, "Python")

        assert len(results) == 1
        assert "Python" in results[0].excerpt
        # Excerpt should be shorter than full content
        assert len(results[0].excerpt) < len(content)

    def test_search_relevance_scoring(self, temp_storage):
        """Test that relevance scoring works."""
        # File with term mentioned once
        temp_storage.write("file1", "Python is mentioned once here")
        # File with term mentioned multiple times
        temp_storage.write(
            "file2", "Python Python Python is mentioned many times Python"
        )

        results = search_memory(temp_storage, "Python")

        # file2 should have higher relevance
        file2_result = next(r for r in results if r.path == "file2")
        file1_result = next(r for r in results if r.path == "file1")
        assert file2_result.relevance_score > file1_result.relevance_score


class TestSplitMemoryNode:
    """Tests for split_memory_node function."""

    def test_split_returns_result(self, temp_storage):
        """Test that split returns a WriteResult."""
        # Create a large file
        large_content = "x" * (SIZE_THRESHOLD + 100)
        temp_storage.write("memory", large_content)

        result = split_memory_node(temp_storage, "memory")

        assert isinstance(result, WriteResult)
        assert result.path == "memory"

    def test_split_nonexistent_file(self, temp_storage):
        """Test splitting a non-existent file."""
        result = split_memory_node(temp_storage, "nonexistent")

        # Should return a result indicating failure
        assert isinstance(result, WriteResult)
        assert result.success is False


class TestIntegration:
    """Integration tests for operations working together."""

    def test_write_search_cycle(self, temp_storage):
        """Test writing content and then searching for it."""
        # Write some content
        agentic_write(temp_storage, "memory", "Python programming information")
        agentic_write(
            temp_storage, "projects/silica", "Silica is a Python agent framework"
        )

        # Search for it
        results = search_memory(temp_storage, "Python")

        assert len(results) >= 2
        paths = [r.path for r in results]
        assert "memory" in paths
        assert "projects/silica" in paths

    def test_write_merge_search(self, temp_storage):
        """Test that merged content is searchable."""
        # Write initial content
        agentic_write(temp_storage, "memory", "Initial Python content")

        # Merge new content
        agentic_write(temp_storage, "memory", "Additional Python details")

        # Search should find both
        results = search_memory(temp_storage, "Python")
        assert len(results) == 1

        content = temp_storage.read("memory")
        assert "Initial" in content
        assert "Additional" in content

    def test_multiple_nested_writes(self, temp_storage):
        """Test writing to multiple nested paths."""
        paths = [
            "memory",
            "projects",
            "projects/silica",
            "projects/webapp",
            "knowledge",
            "knowledge/python",
        ]

        for path in paths:
            result = agentic_write(
                temp_storage, path, f"Content for {path} with Python"
            )
            assert result.success is True

        # All should be searchable
        results = search_memory(temp_storage, "Python")
        assert len(results) == len(paths)
