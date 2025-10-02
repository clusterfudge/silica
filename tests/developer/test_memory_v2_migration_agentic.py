"""
Tests for agentic memory V2 migration.

These tests verify that the migration process:
1. Extracts salient information (not entire files)
2. Writes facts individually to root memory
3. Leverages write_memory for intelligent merging
4. Follows organic growth strategy (root → split when needed)
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from silica.developer.memory_v2.migration import (
    V1MemoryFile,
    extract_and_store_v1_file,
)
from silica.developer.memory_v2.storage import LocalDiskStorage
from silica.developer.context import AgentContext


@pytest.fixture
def temp_storage(tmp_path):
    """Create a temporary storage instance."""
    storage_path = tmp_path / "memory_v2"
    storage_path.mkdir()
    return LocalDiskStorage(base_path=storage_path)


@pytest.fixture
def mock_context():
    """Create a mock AgentContext."""
    context = MagicMock(spec=AgentContext)
    context.usage_summary.return_value = {
        "total_cost": 0.01,
        "total_input_tokens": 100,
        "total_output_tokens": 50,
    }
    return context


@pytest.fixture
def sample_v1_file(tmp_path):
    """Create a sample V1 memory file about a project."""
    v1_file_path = tmp_path / "test.md"
    content = """# Silica Project

## Overview
Silica is an autonomous software engineering agent framework written in Python.
It helps developers by automating code reviews, writing tests, and suggesting improvements.

## Recent Work
- Completed Memory V2 migration on 2025-01-15
- Added support for S3 storage backend
- Improved test coverage to 95%

## Architecture
- Core: AgentContext, MemoryManager, Sandbox
- Storage: Abstract interface with Local and S3 implementations
- Tools: 15+ tools for file operations, git, GitHub, etc.

## Dependencies
- Python 3.11+
- anthropic SDK
- pytest for testing
- ruff for linting

## Next Steps
- Deploy to production
- Add web UI for memory visualization
- Implement cost tracking dashboard
"""

    v1_file_path.write_text(content)

    return V1MemoryFile(
        path="projects/silica.md",
        full_path=v1_file_path,
        size_bytes=len(content),
        last_modified=datetime.now(),
        content=content,
        metadata={"summary": "Silica autonomous agent project"},
    )


@pytest.mark.asyncio
async def test_extract_and_store_uses_agentic_write(
    temp_storage, mock_context, sample_v1_file
):
    """Test that migration writes facts to root using write_memory."""

    # Mock the run_agent function to simulate AI agent behavior
    with patch("silica.developer.tools.subagent.run_agent") as mock_run_agent:
        # Simulate agent extracting facts and writing to root
        async def mock_agent_run(context, prompt, tool_names, system, model):
            # Agent should have write_memory and read_memory
            assert "write_memory" in tool_names
            assert "read_memory" in tool_names
            # No longer needs list_memory_files - just writes to root

            # In real execution, this would call write_memory("", facts)
            return "Agent extracted and wrote facts to root"

        mock_run_agent.side_effect = mock_agent_run

        # Execute migration
        success, message = await extract_and_store_v1_file(
            sample_v1_file, temp_storage, mock_context
        )

        # Verify success
        assert success
        assert "Successfully" in message

        # Verify agent was called with correct tools (only write + read)
        mock_run_agent.assert_called_once()
        call_args = mock_run_agent.call_args
        assert call_args.kwargs["tool_names"] == [
            "write_memory",
            "read_memory",
        ]

        # Verify prompt emphasizes organic growth strategy
        prompt = call_args.kwargs["prompt"]
        assert "extract" in prompt.lower()
        assert "individual facts" in prompt.lower() or "discrete" in prompt.lower()
        assert "root" in prompt.lower() or 'path=""' in prompt


@pytest.mark.asyncio
async def test_migration_prompt_emphasizes_summarization(
    temp_storage, mock_context, sample_v1_file
):
    """Test that migration prompt guides agent to summarize, not dump."""

    with patch("silica.developer.tools.subagent.run_agent") as mock_run_agent:

        async def mock_agent_run(context, prompt, tool_names, system, model):
            # Check that prompt contains key guidance
            assert "extract" in prompt.lower(), "Prompt should mention extraction"

            # Should tell agent NOT to dump everything
            assert any(
                keyword in prompt.lower()
                for keyword in [
                    "don't extract",
                    "redundant",
                    "quality over quantity",
                    "trivial",
                ]
            ), "Prompt should warn against dumping"

            # Should guide on what TO extract
            assert (
                "key facts" in prompt.lower() or "individual facts" in prompt.lower()
            ), "Prompt should mention facts"
            assert (
                "best practices" in prompt.lower()
                or "learnings" in prompt.lower()
                or "insights" in prompt.lower()
            ), "Prompt should mention practices/learnings"

            return "Extracted successfully"

        mock_run_agent.side_effect = mock_agent_run

        success, _ = await extract_and_store_v1_file(
            sample_v1_file, temp_storage, mock_context
        )

        assert success


@pytest.mark.asyncio
async def test_migration_emphasizes_writing_to_root(
    temp_storage, mock_context, sample_v1_file
):
    """Test that migration prompts agent to write facts to root."""

    with patch("silica.developer.tools.subagent.run_agent") as mock_run_agent:

        async def mock_agent_run(context, prompt, tool_names, system, model):
            # Verify prompt emphasizes writing to root
            assert 'path=""' in prompt or "write to root" in prompt.lower()
            assert "organic growth" in prompt.lower()

            # Should mention writing multiple times (one per fact)
            assert (
                "write multiple times" in prompt.lower()
                or "each fact" in prompt.lower()
            )

            return "Facts written to root"

        mock_run_agent.side_effect = mock_agent_run

        success, _ = await extract_and_store_v1_file(
            sample_v1_file, temp_storage, mock_context
        )

        assert success


@pytest.mark.asyncio
async def test_migration_handles_errors_gracefully(
    temp_storage, mock_context, sample_v1_file
):
    """Test that migration handles errors and returns appropriate messages."""

    with patch("silica.developer.tools.subagent.run_agent") as mock_run_agent:
        # Simulate an error during agent execution
        mock_run_agent.side_effect = Exception("AI service unavailable")

        success, message = await extract_and_store_v1_file(
            sample_v1_file, temp_storage, mock_context
        )

        # Should fail gracefully
        assert not success
        assert "Error" in message
        assert "AI service unavailable" in message


@pytest.mark.asyncio
async def test_migration_loads_file_content_on_demand(
    temp_storage, mock_context, tmp_path
):
    """Test that file content is loaded if not already present."""

    # Create V1 file without pre-loaded content
    v1_file_path = tmp_path / "test.md"
    content = "# Test Content\n\nSome important information."
    v1_file_path.write_text(content)

    v1_file = V1MemoryFile(
        path="test.md",
        full_path=v1_file_path,
        size_bytes=len(content),
        last_modified=datetime.now(),
        content=None,  # Not pre-loaded
    )

    with patch("silica.developer.tools.subagent.run_agent") as mock_run_agent:

        async def mock_agent_run(context, prompt, tool_names, system, model):
            # Verify content was loaded and included in prompt
            assert "Test Content" in prompt
            assert "Some important information" in prompt
            return "Success"

        mock_run_agent.side_effect = mock_agent_run

        success, _ = await extract_and_store_v1_file(
            v1_file, temp_storage, mock_context
        )

        assert success
        # Verify content was loaded
        assert v1_file.content == content


@pytest.mark.asyncio
async def test_migration_includes_metadata_in_prompt(
    temp_storage, mock_context, sample_v1_file
):
    """Test that V1 metadata is included in the extraction prompt."""

    # Add metadata to V1 file
    sample_v1_file.metadata = {
        "created": datetime.now().timestamp(),
        "updated": datetime.now().timestamp(),
        "summary": "Important project information",
        "version": "1.0",
    }

    with patch("silica.developer.tools.subagent.run_agent") as mock_run_agent:

        async def mock_agent_run(context, prompt, tool_names, system, model):
            # Verify metadata is in prompt
            assert "Metadata" in prompt
            assert "Summary: Important project information" in prompt
            assert "Version: 1.0" in prompt
            return "Success"

        mock_run_agent.side_effect = mock_agent_run

        success, _ = await extract_and_store_v1_file(
            sample_v1_file, temp_storage, mock_context
        )

        assert success
