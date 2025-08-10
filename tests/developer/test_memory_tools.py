import json
from unittest.mock import MagicMock, patch

import pytest

from silica.developer.context import AgentContext
from silica.developer.tools.memory import (
    read_memory_entry,
    write_memory_entry,
    search_memory,
)
from silica.developer.memory import MemoryManager


@pytest.fixture
def test_memory_manager(tmp_path):
    """Create a memory manager with a temporary memory directory for testing."""
    # Create a memory manager
    memory_manager = MemoryManager(base_dir=tmp_path / "memory")

    # Create some test memory entries
    # Create global memory with new format
    (memory_manager.base_dir / "global.md").write_text("Global memory for testing")
    (memory_manager.base_dir / "global.metadata.json").write_text(
        json.dumps(
            {
                "created": "123456789",
                "updated": "123456789",
                "version": 1,
            }
        )
    )

    # Create a nested directory structure
    projects_dir = memory_manager.base_dir / "projects"
    projects_dir.mkdir(exist_ok=True)

    # Write project1 with new format
    (projects_dir / "project1.md").write_text("Information about project 1")
    (projects_dir / "project1.metadata.json").write_text(
        json.dumps(
            {
                "created": "123456789",
                "updated": "123456789",
                "version": 1,
            }
        )
    )

    # Create a subdirectory
    frontend_dir = projects_dir / "frontend"
    frontend_dir.mkdir(exist_ok=True)

    # Write react with new format
    (frontend_dir / "react.md").write_text("React components and patterns")
    (frontend_dir / "react.metadata.json").write_text(
        json.dumps(
            {
                "created": "123456789",
                "updated": "123456789",
                "version": 1,
            }
        )
    )

    return memory_manager


@pytest.fixture
def mock_context(test_memory_manager):
    """Create a mock AgentContext for testing."""
    context = MagicMock(spec=AgentContext)
    context.report_usage = MagicMock()
    context.memory_manager = test_memory_manager
    context.user_interface = MagicMock()
    return context


def test_get_memory_tree(mock_context):
    """Test getting the memory tree with only node names."""

    result = mock_context.memory_manager.get_tree()

    # Check that the result is structured properly
    assert result["type"] == "tree"
    assert result["success"]

    # Check that the tree items contains expected entries
    tree = result["items"]
    assert "global" in tree
    assert "projects" in tree

    # Verify no content is included, just structure
    assert isinstance(tree["global"], dict)
    assert len(tree["global"]) == 0  # Should be empty as we no longer include content

    # Test with a prefix
    result = mock_context.memory_manager.get_tree("projects")
    tree = result["items"]
    assert "project1" in tree
    assert "frontend" in tree

    # Verify the entry has empty content
    assert isinstance(tree["project1"], dict)
    assert len(tree["project1"]) == 0


def test_write_and_read_memory_entry(mock_context):
    """Test writing and reading memory entries."""
    # Test writing a new entry
    result = write_memory_entry(
        mock_context, "notes/important", "This is an important note"
    )
    assert "successfully" in result.lower()

    # Verify the files were created
    assert (mock_context.memory_manager.base_dir / "notes" / "important.md").exists()
    assert (
        mock_context.memory_manager.base_dir / "notes" / "important.metadata.json"
    ).exists()

    # Test reading the entry
    result = read_memory_entry(mock_context, "notes/important")
    assert "This is an important note" in result

    # Test overwriting an existing entry
    result = write_memory_entry(mock_context, "notes/important", "Updated note content")
    assert "successfully" in result.lower()

    # Verify content was updated
    result = read_memory_entry(mock_context, "notes/important")
    assert "Updated note content" in result

    # Test reading non-existent entry
    result = read_memory_entry(mock_context, "nonexistent/entry")
    assert "Error" in result


@patch("silica.developer.tools.subagent.agent")
async def test_search_memory(mock_agent, mock_context):
    """Test searching memory."""
    # Configure the mock to return a mocked response
    mock_agent.return_value = "Mocked search response"

    # Test searching
    result = await search_memory(mock_context, "project")
    assert result == "Mocked search response"

    # Verify the subagent was called
    mock_agent.assert_called_once()

    # Verify that the model argument was passed correctly
    assert mock_agent.call_args[1]["model"] == "smart"

    # Test searching with prefix
    mock_agent.reset_mock()
    result = await search_memory(mock_context, "react", prefix="projects")
    assert result == "Mocked search response"


@patch("silica.developer.tools.memory.agent")
async def test_critique_memory(mock_agent, mock_context):
    """Test critiquing memory organization."""
    # Configure the mock to return a mocked response
    mock_agent.return_value = "Mocked critique response"

    # Import the function to test
    from silica.developer.tools.memory import critique_memory

    # Test critiquing
    result = await critique_memory(mock_context)
    assert result == "Mocked critique response"

    # Verify the agent was called
    mock_agent.assert_called_once()

    # Verify that the model argument was passed correctly
    assert mock_agent.call_args[1]["model"] == "smart"

    # Check that the prompt contains the expected structural information
    prompt = mock_agent.call_args[1]["prompt"]
    assert "memory organization tree" in prompt
    assert "memory entry paths" in prompt
