"""Test the new memory format."""

import json
import tempfile
from pathlib import Path
import pytest

from silica.developer.memory import MemoryManager


@pytest.fixture
def temp_memory_dir():
    """Create a temporary directory for memory testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


def test_memory_initialization(temp_memory_dir):
    """Test that memory manager initializes correctly with the new format."""
    # Create a memory manager with the test directory
    MemoryManager(base_dir=temp_memory_dir)  # This initializes the memory directory

    # Check that the global memory was created
    assert (temp_memory_dir / "global.md").exists()
    assert (temp_memory_dir / "global.metadata.json").exists()

    # Check content of global memory
    with open(temp_memory_dir / "global.md", "r") as f:
        content = f.read()
    assert "Global memory storage" in content

    # Check metadata of global memory
    with open(temp_memory_dir / "global.metadata.json", "r") as f:
        metadata = json.load(f)
    assert "created" in metadata
    assert "updated" in metadata
    assert "version" in metadata


def test_write_and_read_memory(temp_memory_dir):
    """Test writing and reading memory with the new format."""
    # Create a memory manager with the test directory
    memory_manager = MemoryManager(base_dir=temp_memory_dir)

    # Write a test memory entry
    result = memory_manager.write_entry("test/example", "This is a test memory")
    assert result["success"] is True
    assert "successfully" in result["message"]

    # Check that the files were created
    assert (temp_memory_dir / "test" / "example.md").exists()
    assert (temp_memory_dir / "test" / "example.metadata.json").exists()

    # Read the content file
    with open(temp_memory_dir / "test" / "example.md", "r") as f:
        content = f.read()
    assert content == "This is a test memory"

    # Read the metadata file
    with open(temp_memory_dir / "test" / "example.metadata.json", "r") as f:
        metadata = json.load(f)
    assert "created" in metadata
    assert "updated" in metadata
    assert metadata["version"] == 1

    # Read the memory entry
    result = memory_manager.read_entry("test/example")
    assert result["success"] is True
    assert result["content"] == "This is a test memory"
    assert result["metadata"]["version"] == 1


def test_update_memory(temp_memory_dir):
    """Test updating memory with the new format."""
    # Create a memory manager with the test directory
    memory_manager = MemoryManager(base_dir=temp_memory_dir)

    # Write a test memory entry
    memory_manager.write_entry("test/update", "Original content")

    # Update the memory entry
    result = memory_manager.write_entry("test/update", "Updated content")
    assert result["success"] is True
    assert "successfully" in result["message"]

    # Check the content was updated
    with open(temp_memory_dir / "test" / "update.md", "r") as f:
        content = f.read()
    assert content == "Updated content"

    # Check the metadata was updated
    with open(temp_memory_dir / "test" / "update.metadata.json", "r") as f:
        metadata = json.load(f)
    assert metadata["version"] == 2


def test_delete_memory(temp_memory_dir):
    """Test deleting memory with the new format."""
    # Create a memory manager with the test directory
    memory_manager = MemoryManager(base_dir=temp_memory_dir)

    # Write a test memory entry
    memory_manager.write_entry("test/delete", "Content to delete")

    # Check that the files were created
    assert (temp_memory_dir / "test" / "delete.md").exists()
    assert (temp_memory_dir / "test" / "delete.metadata.json").exists()

    # Delete the memory entry
    result = memory_manager.delete_entry("test/delete")
    assert result["success"] is True
    assert "Successfully deleted" in result["message"]

    # Check that the files were deleted
    assert not (temp_memory_dir / "test" / "delete.md").exists()
    assert not (temp_memory_dir / "test" / "delete.metadata.json").exists()


def test_get_tree(temp_memory_dir):
    """Test getting the memory tree with the new format."""
    # Create a memory manager with the test directory
    memory_manager = MemoryManager(base_dir=temp_memory_dir)

    # Create a few memory entries in different directories
    memory_manager.write_entry("dir1/entry1", "Content 1")
    memory_manager.write_entry("dir1/entry2", "Content 2")
    memory_manager.write_entry("dir2/subdir/entry3", "Content 3")

    # Get the tree
    result = memory_manager.get_tree()
    assert result["success"] is True

    # Get the actual tree items
    tree = result["items"]

    # Check that the tree has the correct structure
    assert "dir1" in tree
    assert "dir2" in tree
    assert "entry1" in tree["dir1"]
    assert "entry2" in tree["dir1"]
    assert "subdir" in tree["dir2"]
