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


async def test_write_and_read_memory_entry(mock_context):
    """Test writing and reading memory entries."""
    # Test writing a new entry
    result = await write_memory_entry(
        mock_context, "This is an important note", path="notes/important"
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
    result = await write_memory_entry(
        mock_context, "Updated note content", path="notes/important"
    )
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


@patch("silica.developer.tools.subagent.agent")
async def test_agentic_write_memory_entry_create_new(mock_agent, mock_context):
    """Test agentic memory placement creating a new entry."""
    # Configure the mock to return a decision to create a new entry
    mock_agent.return_value = """I'll analyze this React components content.

DECISION: CREATE
PATH: projects/frontend/react_library
REASONING: This content describes a React component library which fits well under projects/frontend for web development organization."""

    # Test content to place
    test_content = (
        "# React Component Library\n\nA collection of reusable React components."
    )

    # Test agentic placement
    result = await write_memory_entry(mock_context, test_content)

    # Verify the mock was called
    mock_agent.assert_called_once()
    assert (
        mock_agent.call_args[1]["tool_names"]
        == "get_memory_tree,read_memory_entry,search_memory"
    )
    assert mock_agent.call_args[1]["model"] == "smart"

    # Check the prompt contains the content
    prompt = mock_agent.call_args[1]["prompt"]
    assert "React Component Library" in prompt
    assert "Current memory tree structure:" in prompt

    # Verify the result includes placement information
    assert (
        "Memory entry created successfully at `projects/frontend/react_library`"
        in result
    )
    assert "Placement Reasoning:" in result
    assert "React component library which fits well under projects/frontend" in result


@patch("silica.developer.tools.subagent.agent")
async def test_agentic_write_memory_entry_update_existing(mock_agent, mock_context):
    """Test agentic memory placement updating an existing entry."""
    # Configure the mock to return a decision to update an existing entry
    mock_agent.return_value = """I found similar content that should be updated.

DECISION: UPDATE
PATH: projects/project1
REASONING: This content is very similar to the existing project1 entry and should be merged rather than creating a duplicate."""

    # Test content to place
    test_content = (
        "# Updated Project Information\n\nThis is additional information for project1."
    )

    # Test agentic placement
    result = await write_memory_entry(mock_context, test_content)

    # Verify the mock was called
    mock_agent.assert_called_once()

    # Verify the result includes update information
    assert "Memory entry updated successfully at `projects/project1`" in result
    assert "Placement Reasoning:" in result
    assert "should be merged rather than creating a duplicate" in result


async def test_write_memory_entry_backward_compatibility(mock_context):
    """Test that write_memory_entry maintains backward compatibility when path is provided."""
    # Test with explicit path (should not use agent)
    result = await write_memory_entry(
        mock_context, "Test content", path="explicit/path"
    )

    # Should work exactly like the old version
    assert "successfully" in result.lower()


@patch("silica.developer.tools.subagent.agent")
async def test_agentic_placement_error_handling(mock_agent, mock_context):
    """Test that agentic placement handles errors gracefully."""
    # Configure the mock to raise an exception
    mock_agent.side_effect = Exception("API Error")

    # Test content to place
    test_content = "# Test Content\n\nSome test content."

    # Test agentic placement
    result = await write_memory_entry(mock_context, test_content)

    # Should fallback gracefully
    assert "Memory entry created successfully at `misc/auto_placed`" in result
    assert "Error during agent analysis: API Error" in result
