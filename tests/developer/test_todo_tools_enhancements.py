"""
Tests for the enhanced todo tools.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from silica.developer.tools.todos import (
    TodoItem,
    TodoStatus,
    TodoPriority,
    todo_read,
    todo_add,
    todo_update,
    todo_complete,
    todo_delete,
    format_todo_list,
)


@pytest.fixture
def mock_context():
    """Create a mock context with a session ID."""
    context = MagicMock()
    context.session_id = "test-session"
    return context


@pytest.fixture
def sample_todos():
    """Create a sample list of todos."""
    return [
        TodoItem(
            id="1",
            content="Implement todo tools",
            status=TodoStatus.IN_PROGRESS,
            priority=TodoPriority.HIGH,
        ),
        TodoItem(
            id="2",
            content="Write tests",
            status=TodoStatus.PENDING,
            priority=TodoPriority.MEDIUM,
        ),
        TodoItem(
            id="3",
            content="Update docs",
            status=TodoStatus.COMPLETED,
            priority=TodoPriority.LOW,
        ),
    ]


def test_format_todo_list(sample_todos):
    """Test that format_todo_list includes metadata."""
    result = format_todo_list(sample_todos)

    # Check that the function returns a string with the expected content
    assert "# Todo List" in result
    assert "Implement todo tools" in result
    assert "Write tests" in result
    assert "Update docs" in result

    # Check that metadata is included
    assert "## METADATA" in result
    assert "```json" in result

    # Extract and parse the metadata
    metadata_start = result.find("```json") + 7
    metadata_end = result.find("```", metadata_start)
    metadata_json = result[metadata_start:metadata_end].strip()
    metadata = json.loads(metadata_json)

    # Verify metadata structure
    assert "todos" in metadata
    assert len(metadata["todos"]) == 3
    assert metadata["todos"][0]["id"] == "1"
    assert metadata["todos"][0]["content"] == "Implement todo tools"
    assert metadata["todos"][0]["status"] == "in_progress"
    assert metadata["todos"][0]["priority"] == "high"


@patch("silica.developer.tools.todos.load_todos")
@patch("silica.developer.tools.todos.save_todos")
def test_todo_add(mock_save_todos, mock_load_todos, mock_context, sample_todos):
    """Test adding a new todo."""
    # Setup
    mock_load_todos.return_value = sample_todos.copy()

    # Execute
    result = todo_add(mock_context, "Review PR", "high")

    # Verify
    assert "✅ Added todo" in result
    assert "Review PR" in result
    assert "high" in result

    # Check that save_todos was called with the correct arguments
    args = mock_save_todos.call_args[0]
    saved_todos = args[1]
    assert len(saved_todos) == 4  # 3 original + 1 new
    assert saved_todos[3].content == "Review PR"
    assert saved_todos[3].priority == TodoPriority.HIGH
    assert saved_todos[3].status == TodoStatus.PENDING


@patch("silica.developer.tools.todos.load_todos")
@patch("silica.developer.tools.todos.save_todos")
def test_todo_update(mock_save_todos, mock_load_todos, mock_context, sample_todos):
    """Test updating a todo."""
    # Setup
    mock_load_todos.return_value = sample_todos.copy()

    # Execute - update content and priority
    result = todo_update(
        mock_context, todo_id="2", content="Write comprehensive tests", priority="high"
    )

    # Verify
    assert "✅ Updated todo" in result
    assert "Write comprehensive tests" in result
    assert "priority: 'medium' → 'high'" in result

    # Check that save_todos was called with the correct arguments
    args = mock_save_todos.call_args[0]
    saved_todos = args[1]
    updated_todo = next(todo for todo in saved_todos if todo.id == "2")
    assert updated_todo.content == "Write comprehensive tests"
    assert updated_todo.priority == TodoPriority.HIGH


@patch("silica.developer.tools.todos.load_todos")
@patch("silica.developer.tools.todos.save_todos")
def test_todo_complete(mock_save_todos, mock_load_todos, mock_context, sample_todos):
    """Test marking a todo as completed."""
    # Setup
    mock_load_todos.return_value = sample_todos.copy()

    # Execute
    result = todo_complete(mock_context, todo_id="2")

    # Verify
    assert "✅ Marked todo as completed" in result
    assert "Write tests" in result
    assert "status: 'pending' → 'completed'" in result

    # Check that save_todos was called with the correct arguments
    args = mock_save_todos.call_args[0]
    saved_todos = args[1]
    completed_todo = next(todo for todo in saved_todos if todo.id == "2")
    assert completed_todo.status == TodoStatus.COMPLETED


@patch("silica.developer.tools.todos.load_todos")
@patch("silica.developer.tools.todos.save_todos")
def test_todo_delete(mock_save_todos, mock_load_todos, mock_context, sample_todos):
    """Test deleting a todo."""
    # Setup
    mock_load_todos.return_value = sample_todos.copy()

    # Execute
    result = todo_delete(mock_context, todo_id="1")

    # Verify
    assert "✅ Deleted todo" in result
    assert "Implement todo tools" in result

    # Check that save_todos was called with the correct arguments
    args = mock_save_todos.call_args[0]
    saved_todos = args[1]
    assert len(saved_todos) == 2  # 3 original - 1 deleted
    assert all(todo.id != "1" for todo in saved_todos)


@patch("silica.developer.tools.todos.load_todos")
def test_todo_read(mock_load_todos, mock_context, sample_todos):
    """Test reading todos with metadata."""
    # Setup
    mock_load_todos.return_value = sample_todos.copy()

    # Execute
    result = todo_read(mock_context)

    # Verify the result contains the todo list and metadata
    assert "# Todo List" in result
    assert "Implement todo tools" in result
    assert "## METADATA" in result

    # Extract and verify metadata
    metadata_start = result.find("```json") + 7
    metadata_end = result.find("```", metadata_start)
    metadata_json = result[metadata_start:metadata_end].strip()
    metadata = json.loads(metadata_json)

    assert len(metadata["todos"]) == 3
    assert (
        metadata["todos"][0]["id"] == "1"
    )  # First item should be the in_progress high priority task
