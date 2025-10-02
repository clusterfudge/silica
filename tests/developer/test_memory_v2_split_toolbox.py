"""
Tests for the split_memory specialized toolbox.

The split agent needs direct storage access (not agentic operations)
to avoid recursive AI calls during the split process.
"""

import tempfile
from unittest.mock import Mock

import pytest

from silica.developer.context import AgentContext
from silica.developer.memory_v2 import MemoryManager
from silica.developer.memory_v2.operations import create_split_toolbox


@pytest.fixture
def temp_storage():
    """Create a temporary storage instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = MemoryManager(base_path=tmpdir)
        yield manager.storage


@pytest.fixture
def mock_context(temp_storage):
    """Create a mock context with storage."""
    context = Mock(spec=AgentContext)
    context.memory_manager = Mock()
    context.memory_manager.storage = temp_storage
    return context


class TestSplitToolbox:
    """Tests for create_split_toolbox()."""

    def test_creates_toolbox_with_correct_tools(self, temp_storage):
        """Test that toolbox contains exactly the tools we need."""
        tools = create_split_toolbox(temp_storage)

        # Should have exactly 3 tools
        assert len(tools) == 3
        tool_names = [t.__name__ for t in tools]
        assert "_memory_read" in tool_names
        assert "_memory_write" in tool_names
        assert "_memory_list" in tool_names

    def test_toolbox_tools_have_correct_metadata(self, temp_storage):
        """Test that tools have proper names and descriptions."""
        tools = create_split_toolbox(temp_storage)

        read_tool = next(t for t in tools if t.__name__ == "_memory_read")
        assert "read" in read_tool.__doc__.lower()
        assert "path" in read_tool.__doc__.lower()

        write_tool = next(t for t in tools if t.__name__ == "_memory_write")
        assert "write" in write_tool.__doc__.lower()
        assert "content" in write_tool.__doc__.lower()

        list_tool = next(t for t in tools if t.__name__ == "_memory_list")
        assert "list" in list_tool.__doc__.lower()

    def test_toolbox_is_isolated(self, temp_storage):
        """Test that toolbox tools are independent instances."""
        tools1 = create_split_toolbox(temp_storage)
        tools2 = create_split_toolbox(temp_storage)

        # Different tool list instances
        assert tools1 is not tools2

        # But should have same tool names
        names1 = [t.__name__ for t in tools1]
        names2 = [t.__name__ for t in tools2]
        assert names1 == names2


class TestMemoryReadTool:
    """Tests for _memory_read internal tool."""

    def test_read_existing_content(self, temp_storage, mock_context):
        """Test reading existing memory content."""
        # Setup: write some content
        temp_storage.write("test", "Test content")

        # Create toolbox and get read tool
        tools = create_split_toolbox(temp_storage)
        read_tool = next(t for t in tools if t.__name__ == "_memory_read")

        # Execute tool
        result = read_tool(mock_context, path="test")

        # Should return content with metadata
        assert "Test content" in result
        assert "test" in result
        assert "bytes" in result.lower()

    def test_read_nonexistent_returns_error(self, temp_storage, mock_context):
        """Test reading nonexistent file returns helpful error."""
        tools = create_split_toolbox(temp_storage)
        read_tool = next(t for t in tools if t.__name__ == "_memory_read")

        result = read_tool(mock_context, path="nonexistent")

        assert "error" in result.lower()
        assert "nonexistent" in result

    def test_read_empty_path_reads_root(self, temp_storage, mock_context):
        """Test that empty path reads root."""
        temp_storage.write("", "Root content")

        tools = create_split_toolbox(temp_storage)
        read_tool = next(t for t in tools if t.__name__ == "_memory_read")

        result = read_tool(mock_context, path="")

        assert "Root content" in result


class TestMemoryWriteTool:
    """Tests for _memory_write internal tool."""

    def test_write_new_content(self, temp_storage, mock_context):
        """Test writing new content directly."""
        tools = create_split_toolbox(temp_storage)
        write_tool = next(t for t in tools if t.__name__ == "_memory_write")

        result = write_tool(mock_context, path="test", content="New content")

        # Should confirm success
        assert "✅" in result or "success" in result.lower()
        assert "test" in result

        # Content should be written
        assert temp_storage.read("test") == "New content"

    def test_write_overwrites_existing(self, temp_storage, mock_context):
        """Test that write replaces existing content (no merging)."""
        temp_storage.write("test", "Old content")

        tools = create_split_toolbox(temp_storage)
        write_tool = next(t for t in tools if t.__name__ == "_memory_write")

        write_tool(mock_context, path="test", content="New content")

        # Should completely replace (not merge)
        assert temp_storage.read("test") == "New content"

    def test_write_creates_parent_directories(self, temp_storage, mock_context):
        """Test writing to nested path creates parents."""
        tools = create_split_toolbox(temp_storage)
        write_tool = next(t for t in tools if t.__name__ == "_memory_write")

        write_tool(mock_context, path="a/b/c", content="Nested")

        assert temp_storage.read("a/b/c") == "Nested"

    def test_write_to_root(self, temp_storage, mock_context):
        """Test writing to root (empty path)."""
        tools = create_split_toolbox(temp_storage)
        write_tool = next(t for t in tools if t.__name__ == "_memory_write")

        result = write_tool(mock_context, path="", content="Root content")

        assert "✅" in result or "success" in result.lower()
        assert temp_storage.read("") == "Root content"


class TestMemoryListTool:
    """Tests for _memory_list internal tool."""

    def test_list_empty_storage(self, temp_storage, mock_context):
        """Test listing when no files exist."""
        tools = create_split_toolbox(temp_storage)
        list_tool = next(t for t in tools if t.__name__ == "_memory_list")

        result = list_tool(mock_context)

        assert "no memory" in result.lower() or "empty" in result.lower()

    def test_list_shows_existing_files(self, temp_storage, mock_context):
        """Test listing shows all existing files."""
        temp_storage.write("", "Root")
        temp_storage.write("projects", "Projects")
        temp_storage.write("projects/silica", "Silica")

        tools = create_split_toolbox(temp_storage)
        list_tool = next(t for t in tools if t.__name__ == "_memory_list")

        result = list_tool(mock_context)

        # Should list all paths
        assert "projects" in result
        assert "projects/silica" in result
        # Root might be shown as "" or "memory" or similar

    def test_list_shows_sizes(self, temp_storage, mock_context):
        """Test that list shows file sizes."""
        temp_storage.write("test", "Content here")

        tools = create_split_toolbox(temp_storage)
        list_tool = next(t for t in tools if t.__name__ == "_memory_list")

        result = list_tool(mock_context)

        assert "bytes" in result.lower() or "kb" in result.lower()


class TestToolboxIntegration:
    """Integration tests for the split toolbox."""

    def test_write_then_read_cycle(self, temp_storage, mock_context):
        """Test writing then reading through toolbox."""
        tools = create_split_toolbox(temp_storage)
        write_tool = next(t for t in tools if t.__name__ == "_memory_write")
        read_tool = next(t for t in tools if t.__name__ == "_memory_read")

        # Write content
        write_tool(mock_context, path="test", content="Test content")

        # Read it back
        result = read_tool(mock_context, path="test")

        assert "Test content" in result

    def test_multiple_writes_then_list(self, temp_storage, mock_context):
        """Test writing multiple files then listing."""
        tools = create_split_toolbox(temp_storage)
        write_tool = next(t for t in tools if t.__name__ == "_memory_write")
        list_tool = next(t for t in tools if t.__name__ == "_memory_list")

        # Write several files
        write_tool(mock_context, path="file1", content="Content 1")
        write_tool(mock_context, path="file2", content="Content 2")
        write_tool(mock_context, path="nested/file3", content="Content 3")

        # List should show all
        result = list_tool(mock_context)

        assert "file1" in result
        assert "file2" in result
        assert "nested/file3" in result

    def test_tools_share_same_storage(self, temp_storage, mock_context):
        """Test that all tools in toolbox operate on same storage."""
        tools = create_split_toolbox(temp_storage)
        write_tool = next(t for t in tools if t.__name__ == "_memory_write")
        read_tool = next(t for t in tools if t.__name__ == "_memory_read")

        # Write through one tool
        write_tool(mock_context, path="shared", content="Shared content")

        # Read through another tool - should see the same content
        result = read_tool(mock_context, path="shared")

        assert "Shared content" in result

        # Also verify through direct storage access
        assert temp_storage.read("shared") == "Shared content"
