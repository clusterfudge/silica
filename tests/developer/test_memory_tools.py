import json
from unittest.mock import MagicMock, patch

import pytest

from silica.developer.context import AgentContext
from silica.developer.tools.memory import (
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

    # Mock the write_entry method to track calls
    context.memory_manager.write_entry = MagicMock()
    context.memory_manager.write_entry.return_value = {
        "success": True,
        "message": "Memory entry written successfully",
    }

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


@patch("silica.developer.tools.subagent.agent")
async def test_write_memory_entry_with_summary_integration(mock_agent, mock_context):
    """Test that write_memory_entry generates and includes summaries properly."""
    # Configure the mock to return a summary
    mock_agent.return_value = "An important note for testing purposes."

    # Test writing a new entry with explicit path
    result = await write_memory_entry(
        mock_context, "This is an important note", path="notes/important"
    )

    # Should include summary in response
    assert "successfully" in result.lower()
    assert "Content Summary:" in result
    assert "important note for testing" in result

    # Verify the summary was passed to write_entry in metadata
    write_calls = mock_context.memory_manager.write_entry.call_args_list
    assert len(write_calls) == 1
    path, content, metadata = write_calls[0][0]
    assert path == "notes/important"
    assert content == "This is an important note"
    assert "summary" in metadata
    assert "important note for testing" in metadata["summary"]

    # Reset the mock for second test
    mock_context.memory_manager.write_entry.reset_mock()
    mock_agent.return_value = "Updated note content for testing."

    # Test overwriting an existing entry
    result = await write_memory_entry(
        mock_context, "Updated note content", path="notes/important"
    )
    assert "successfully" in result.lower()
    assert "Content Summary:" in result
    assert "Updated note content for testing" in result

    # Verify the updated summary was passed
    write_calls = mock_context.memory_manager.write_entry.call_args_list
    assert len(write_calls) == 1
    path, content, metadata = write_calls[0][0]
    assert path == "notes/important"
    assert content == "Updated note content"
    assert "summary" in metadata
    assert "Updated note content for testing" in metadata["summary"]


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
    """Test agentic memory placement creating a new entry with summary."""
    # Configure the mock to return a decision with summary
    mock_agent.return_value = """I'll analyze this React components content.

DECISION: CREATE
PATH: projects/frontend/react_library
SUMMARY: A collection of reusable React components for web applications including buttons, modals, and form inputs.
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

    # Check the prompt contains the content and asks for summary
    prompt = mock_agent.call_args[1]["prompt"]
    assert "React Component Library" in prompt
    assert "Current memory tree structure:" in prompt
    assert "SUMMARY:" in prompt

    # Verify the result includes placement information and summary
    assert (
        "Memory entry created successfully at `projects/frontend/react_library`"
        in result
    )
    assert "Content Summary:" in result
    assert "reusable React components for web applications" in result
    assert "Placement Reasoning:" in result
    assert "React component library which fits well under projects/frontend" in result

    # Verify the summary was passed to write_entry in metadata
    write_calls = mock_context.memory_manager.write_entry.call_args_list
    assert len(write_calls) == 1
    path, content, metadata = write_calls[0][0]
    assert path == "projects/frontend/react_library"
    assert "summary" in metadata
    assert "reusable React components" in metadata["summary"]


@patch("silica.developer.tools.subagent.agent")
async def test_agentic_write_memory_entry_update_existing(mock_agent, mock_context):
    """Test agentic memory placement updating an existing entry with summary."""
    # Configure the mock to return a decision to update with summary
    mock_agent.return_value = """I found similar content that should be updated.

DECISION: UPDATE
PATH: projects/project1
SUMMARY: Updated project information with additional details and context.
REASONING: This content is very similar to the existing project1 entry and should be merged rather than creating a duplicate."""

    # Test content to place
    test_content = (
        "# Updated Project Information\n\nThis is additional information for project1."
    )

    # Test agentic placement
    result = await write_memory_entry(mock_context, test_content)

    # Verify the mock was called
    mock_agent.assert_called_once()

    # Verify the result includes update information and summary
    assert "Memory entry updated successfully at `projects/project1`" in result
    assert "Content Summary:" in result
    assert "Updated project information with additional details" in result
    assert "Placement Reasoning:" in result
    assert "should be merged rather than creating a duplicate" in result

    # Verify the summary was passed to write_entry in metadata
    write_calls = mock_context.memory_manager.write_entry.call_args_list
    assert len(write_calls) == 1
    path, content, metadata = write_calls[0][0]
    assert path == "projects/project1"
    assert "summary" in metadata
    assert "Updated project information" in metadata["summary"]


@patch("silica.developer.tools.subagent.agent")
async def test_write_memory_entry_explicit_path_with_summary(mock_agent, mock_context):
    """Test that write_memory_entry generates summary when path is explicitly provided."""
    # Configure the mock to return a summary
    mock_agent.return_value = "A simple test content entry for verification purposes."

    # Test with explicit path (should generate summary)
    result = await write_memory_entry(
        mock_context, "Test content for memory", path="explicit/path"
    )

    # Verify the agent was called for summary generation
    mock_agent.assert_called_once()
    prompt = mock_agent.call_args[1]["prompt"]
    assert "Test content for memory" in prompt
    assert "concise summary" in prompt

    # Should work and include summary
    assert "successfully" in result.lower()
    assert "Content Summary:" in result
    assert "simple test content entry" in result

    # Verify the summary was passed to write_entry in metadata
    write_calls = mock_context.memory_manager.write_entry.call_args_list
    assert len(write_calls) == 1
    path, content, metadata = write_calls[0][0]
    assert path == "explicit/path"
    assert "summary" in metadata
    assert "simple test content entry" in metadata["summary"]


@patch("silica.developer.tools.subagent.agent")
async def test_agentic_placement_error_handling(mock_agent, mock_context):
    """Test that agentic placement surfaces errors properly."""
    # Configure the mock to raise an exception
    mock_agent.side_effect = Exception("API Error")

    # Test content to place
    test_content = "# Test Content\n\nSome test content."

    # Test agentic placement
    result = await write_memory_entry(mock_context, test_content)

    # Should surface the error instead of falling back
    assert "Error: Could not determine memory placement:" in result
    assert "API Error" in result


@patch("silica.developer.tools.subagent.agent")
async def test_agentic_placement_invalid_response(mock_agent, mock_context):
    """Test that agentic placement handles invalid agent responses properly."""
    # Configure the mock to return an invalid response (missing PATH)
    mock_agent.return_value = """I'll analyze this content.

DECISION: CREATE
REASONING: This seems like good content but I forgot to specify a path."""

    # Test content to place
    test_content = "# Test Content\n\nSome test content."

    # Test agentic placement
    result = await write_memory_entry(mock_context, test_content)

    # Should surface the error about invalid response
    assert "Error: Could not determine memory placement:" in result
    assert "Agent did not provide a valid path" in result


@patch("silica.developer.tools.subagent.agent")
async def test_agentic_placement_invalid_response_missing_path(
    mock_agent, mock_context
):
    """Test that agentic placement handles invalid agent responses missing PATH."""
    # Configure the mock to return an invalid response (missing PATH)
    mock_agent.return_value = """I'll analyze this content.

DECISION: CREATE
SUMMARY: Test content for demonstration purposes.
REASONING: This seems like good content but I forgot to specify a path."""

    # Test content to place
    test_content = "# Test Content\n\nSome test content."

    # Test agentic placement
    result = await write_memory_entry(mock_context, test_content)

    # Should surface the error about invalid response
    assert "Error: Could not determine memory placement:" in result
    assert "Agent did not provide a valid path" in result


@patch("silica.developer.tools.subagent.agent")
async def test_agentic_placement_invalid_response_missing_summary(
    mock_agent, mock_context
):
    """Test that agentic placement handles invalid agent responses missing SUMMARY."""
    # Configure the mock to return an invalid response (missing SUMMARY)
    mock_agent.return_value = """I'll analyze this content.

DECISION: CREATE
PATH: test/path
REASONING: This seems like good content but I forgot to provide a summary."""

    # Test content to place
    test_content = "# Test Content\n\nSome test content."

    # Test agentic placement
    result = await write_memory_entry(mock_context, test_content)

    # Should surface the error about invalid response
    assert "Error: Could not determine memory placement:" in result
    assert "Agent did not provide a valid summary" in result


@patch("silica.developer.tools.subagent.agent")
async def test_explicit_path_summary_generation_error(mock_agent, mock_context):
    """Test explicit path handling when summary generation fails."""
    # Configure the mock to raise an exception for summary generation
    mock_agent.side_effect = Exception("Summary generation failed")

    # Test content to place
    test_content = "# Test Content\n\nSome test content."

    # Test explicit path with summary generation failure
    result = await write_memory_entry(mock_context, test_content, path="test/path")

    # Should fall back gracefully and still write the entry
    assert "successfully" in result.lower()
    assert "Note:" in result
    assert "Could not generate summary" in result
    assert "Summary generation failed" in result

    # Verify entry was still written without summary in metadata
    write_calls = mock_context.memory_manager.write_entry.call_args_list
    assert len(write_calls) == 1
    # When summary generation fails, write_entry is called with just path and content
    args = write_calls[0][0]
    assert len(args) == 2  # Only path and content, no metadata
    path, content = args
    assert path == "test/path"
    assert content == "# Test Content\n\nSome test content."
