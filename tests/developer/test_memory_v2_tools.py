"""
Tests for Memory V2 tools.
"""

import tempfile
from unittest.mock import Mock

import pytest

from silica.developer.context import AgentContext
from silica.developer.memory_v2 import MemoryManager
from silica.developer.tools.memory_v2_tools import (
    read_memory,
    write_memory,
    list_memory_files,
    delete_memory,
)


@pytest.fixture
def temp_context():
    """Create a temporary context with isolated memory storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        context = Mock(spec=AgentContext)
        # Set up isolated memory manager for this test
        context.memory_manager = MemoryManager(base_path=tmpdir)
        yield context


class TestReadMemory:
    """Tests for read_memory tool."""

    def test_read_root_memory(self, temp_context):
        """Test reading root memory file."""
        # Setup: create root memory
        storage = temp_context.memory_manager.storage
        storage.write("memory", "Root content")

        # Test: read with empty path
        result = read_memory(temp_context, "")
        assert result == "Root content"

    def test_read_nested_memory(self, temp_context):
        """Test reading nested memory file."""
        storage = temp_context.memory_manager.storage
        storage.write("projects/silica", "Silica content")

        result = read_memory(temp_context, "projects/silica")
        assert result == "Silica content"

    def test_read_nonexistent_returns_error(self, temp_context):
        """Test that reading nonexistent file returns helpful error."""
        result = read_memory(temp_context, "nonexistent")

        assert "❌" in result
        assert "not found" in result.lower()
        assert "list_memory_files()" in result

    def test_read_with_default_path(self, temp_context):
        """Test reading with no path argument defaults to root."""
        storage = temp_context.memory_manager.storage
        storage.write("memory", "Default content")

        result = read_memory(temp_context)
        assert result == "Default content"


class TestWriteMemory:
    """Tests for write_memory tool."""

    def test_write_root_memory(self, temp_context):
        """Test writing to root memory."""
        result = write_memory(temp_context, "Test content", "")

        assert "✅" in result
        assert "memory" in result
        storage = temp_context.memory_manager.storage
        assert storage.read("memory") == "Test content"

    def test_write_nested_memory(self, temp_context):
        """Test writing to nested path."""
        result = write_memory(
            temp_context, "Nested content", "projects/silica/architecture"
        )

        assert "✅" in result
        storage = temp_context.memory_manager.storage
        assert storage.read("projects/silica/architecture") == "Nested content"

    def test_write_shows_size_info(self, temp_context):
        """Test that write result includes size information."""
        result = write_memory(temp_context, "Small content", "test")

        assert "📊" in result
        assert "KB" in result
        assert "bytes" in result

    def test_write_warns_on_large_file(self, temp_context):
        """Test warning when file exceeds 10KB threshold."""
        # Create content > 10KB
        large_content = "x" * 11000

        result = write_memory(temp_context, large_content, "large")

        assert "⚠️" in result
        assert "10kb" in result.lower()
        assert "split" in result.lower()

    def test_write_warns_approaching_threshold(self, temp_context):
        """Test warning when file approaches 10KB threshold."""
        # Create content > 8KB but < 10KB
        medium_content = "x" * 9000

        result = write_memory(temp_context, medium_content, "medium")

        assert "💡" in result
        assert "getting large" in result.lower()

    def test_write_overwrites_existing(self, temp_context):
        """Test that write replaces existing content by default."""
        write_memory(temp_context, "Original", "test")
        write_memory(temp_context, "Updated", "test")

        storage = temp_context.memory_manager.storage
        assert storage.read("test") == "Updated"

    def test_write_append_mode(self, temp_context):
        """Test append mode adds to existing content."""
        write_memory(temp_context, "First", "test")
        write_memory(temp_context, "Second", "test", append=True)

        storage = temp_context.memory_manager.storage
        assert storage.read("test") == "FirstSecond"

    def test_write_append_to_nonexistent_creates_new(self, temp_context):
        """Test append mode creates new file if it doesn't exist."""
        write_memory(temp_context, "Content", "new", append=True)

        storage = temp_context.memory_manager.storage
        assert storage.read("new") == "Content"

    def test_write_empty_content(self, temp_context):
        """Test writing empty content is allowed."""
        result = write_memory(temp_context, "", "empty")

        assert "✅" in result
        storage = temp_context.memory_manager.storage
        assert storage.read("empty") == ""

    def test_write_unicode_content(self, temp_context):
        """Test writing Unicode content."""
        content = "Hello 世界 🌍"
        write_memory(temp_context, content, "unicode")

        storage = temp_context.memory_manager.storage
        assert storage.read("unicode") == content

    def test_write_with_default_path(self, temp_context):
        """Test writing with no path defaults to root."""
        result = write_memory(temp_context, "Default content")

        assert "✅" in result
        storage = temp_context.memory_manager.storage
        assert storage.read("memory") == "Default content"


class TestListMemoryFiles:
    """Tests for list_memory_files tool."""

    def test_list_empty_memory(self, temp_context):
        """Test listing when no memory files exist."""
        result = list_memory_files(temp_context)

        assert "📭" in result
        assert "No memory files found" in result
        assert "write_memory" in result

    def test_list_single_file(self, temp_context):
        """Test listing with single memory file."""
        storage = temp_context.memory_manager.storage
        storage.write("memory", "Content")

        result = list_memory_files(temp_context)

        assert "memory" in result
        assert "KB" in result
        assert "Total: 1 file" in result

    def test_list_multiple_files(self, temp_context):
        """Test listing multiple memory files."""
        storage = temp_context.memory_manager.storage
        storage.write("memory", "Root")
        storage.write("projects", "Projects")
        storage.write("projects/silica", "Silica")

        result = list_memory_files(temp_context)

        assert "memory" in result
        assert "projects" in result
        assert "projects/silica" in result
        assert "Total: 3 file" in result

    def test_list_shows_size_info(self, temp_context):
        """Test that list shows size information."""
        storage = temp_context.memory_manager.storage
        storage.write("test", "Some content")

        result = list_memory_files(temp_context)

        assert "📊" in result
        assert "KB" in result

    def test_list_shows_date_info(self, temp_context):
        """Test that list shows date information."""
        storage = temp_context.memory_manager.storage
        storage.write("test", "Content")

        result = list_memory_files(temp_context)

        assert "📅" in result
        # Should have a date in format YYYY-MM-DD
        import re

        assert re.search(r"\d{4}-\d{2}-\d{2}", result)

    def test_list_warns_on_large_files(self, temp_context):
        """Test that list warns about large files."""
        storage = temp_context.memory_manager.storage
        large_content = "x" * 11000
        storage.write("large", large_content)

        result = list_memory_files(temp_context)

        assert "⚠️" in result
        assert "10KB" in result

    def test_list_warns_on_medium_files(self, temp_context):
        """Test that list warns about files approaching threshold."""
        storage = temp_context.memory_manager.storage
        medium_content = "x" * 9000
        storage.write("medium", medium_content)

        result = list_memory_files(temp_context)

        assert "💡" in result
        assert "Getting large" in result


class TestDeleteMemory:
    """Tests for delete_memory tool."""

    def test_delete_existing_file(self, temp_context):
        """Test deleting an existing file."""
        storage = temp_context.memory_manager.storage
        storage.write("test", "Content")

        result = delete_memory(temp_context, "test")

        assert "✅" in result
        assert "deleted" in result.lower()
        assert not storage.exists("test")

    def test_delete_nonexistent_returns_error(self, temp_context):
        """Test that deleting nonexistent file returns error."""
        result = delete_memory(temp_context, "nonexistent")

        assert "❌" in result
        assert "not found" in result.lower()
        assert "list_memory_files()" in result

    def test_delete_preserves_children(self, temp_context):
        """Test that deleting parent preserves children."""
        storage = temp_context.memory_manager.storage
        storage.write("parent", "Parent content")
        storage.write("parent/child", "Child content")

        delete_memory(temp_context, "parent")

        # Parent should be deleted
        assert not storage.exists("parent")
        # Child should still exist
        assert storage.exists("parent/child")

    def test_delete_nested_file(self, temp_context):
        """Test deleting nested file."""
        storage = temp_context.memory_manager.storage
        storage.write("a/b/c", "Deep content")

        result = delete_memory(temp_context, "a/b/c")

        assert "✅" in result
        assert not storage.exists("a/b/c")


class TestToolIntegration:
    """Integration tests for multiple tools working together."""

    def test_write_read_cycle(self, temp_context):
        """Test writing then reading content."""
        write_memory(temp_context, "Test content", "test")
        result = read_memory(temp_context, "test")

        assert result == "Test content"

    def test_write_list_read_delete_cycle(self, temp_context):
        """Test full lifecycle of memory operations."""
        # Write
        write_result = write_memory(temp_context, "Content", "test")
        assert "✅" in write_result

        # List
        list_result = list_memory_files(temp_context)
        assert "test" in list_result

        # Read
        read_result = read_memory(temp_context, "test")
        assert read_result == "Content"

        # Delete
        delete_result = delete_memory(temp_context, "test")
        assert "✅" in delete_result

        # Verify deleted
        list_result2 = list_memory_files(temp_context)
        assert "No memory files found" in list_result2

    def test_parent_child_operations(self, temp_context):
        """Test operations on parent and child nodes."""
        # Create parent
        write_memory(temp_context, "Parent", "projects")

        # Create children
        write_memory(temp_context, "Silica", "projects/silica")
        write_memory(temp_context, "Personal", "projects/personal")

        # List should show all
        list_result = list_memory_files(temp_context)
        assert "projects" in list_result
        assert "projects/silica" in list_result
        assert "projects/personal" in list_result

        # Read each
        assert read_memory(temp_context, "projects") == "Parent"
        assert read_memory(temp_context, "projects/silica") == "Silica"
        assert read_memory(temp_context, "projects/personal") == "Personal"

    def test_organic_growth_scenario(self, temp_context):
        """Test organic growth from simple to complex."""
        # Start simple
        write_memory(temp_context, "Initial thoughts", "memory")

        # Grow
        write_memory(temp_context, "Updated thoughts with more context", "memory")

        # Split into topics
        write_memory(temp_context, "Project info", "memory/projects")
        write_memory(temp_context, "Knowledge base", "memory/knowledge")

        # Verify structure
        list_result = list_memory_files(temp_context)
        assert "memory" in list_result
        assert "memory/projects" in list_result
        assert "memory/knowledge" in list_result

        # All should be readable
        assert "Updated thoughts" in read_memory(temp_context, "memory")
        assert "Project info" in read_memory(temp_context, "memory/projects")
        assert "Knowledge base" in read_memory(temp_context, "memory/knowledge")
