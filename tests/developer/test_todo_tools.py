import json
import uuid
from unittest import mock

import pytest

from silica.developer.context import AgentContext
from silica.developer.tools.todos import (
    todo_read,
    todo_write,
    TodoItem,
    TodoStatus,
    TodoPriority,
)


@pytest.fixture
def mock_session_id():
    return str(uuid.uuid4())


@pytest.fixture
def mock_context(mock_session_id):
    context = mock.MagicMock(spec=AgentContext)
    context.session_id = mock_session_id
    return context


@pytest.fixture
def mock_todo_file(tmp_path, mock_session_id):
    # Create a temporary directory for todos
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()

    # Create a mock todo file
    todo_file = todos_dir / f"{mock_session_id}.json"

    # Mock the get_todos_dir function to return our temp directory
    with mock.patch(
        "silica.developer.tools.todos.get_todos_dir", return_value=todos_dir
    ):
        yield todo_file


def test_todo_read_empty(mock_context, mock_todo_file):
    """Test reading an empty todo list."""
    # Ensure the file doesn't exist yet
    assert not mock_todo_file.exists()

    # Call todo_read
    result = todo_read(mock_context)

    # Check the result
    assert "No todos in the current session." in result


def test_todo_write_and_read(mock_context, mock_todo_file):
    """Test writing and then reading todos."""
    # Create some todos
    todos_data = [
        {"content": "Task 1", "priority": "high"},
        {"content": "Task 2", "status": "in_progress"},
        {"content": "Task 3", "priority": "low", "status": "completed"},
    ]

    # Write the todos
    write_result = todo_write(mock_context, todos_data)

    # Check that the file was created
    assert mock_todo_file.exists()

    # Verify the write result contains expected changes
    assert "Added" in write_result
    assert "Task 1" in write_result
    assert "Task 2" in write_result
    assert "Task 3" in write_result

    # Read the todos
    read_result = todo_read(mock_context)

    # Check the read result contains our todos, properly sorted
    assert "Task 2" in read_result  # in_progress should be first
    assert "Task 1" in read_result  # high priority should be second
    assert "Task 3" in read_result  # completed should be last

    # Check the status indicators
    assert "[→]" in read_result  # for in_progress
    assert "[ ]" in read_result  # for pending
    assert "[✓]" in read_result  # for completed


def test_todo_update(mock_context, mock_todo_file):
    """Test updating existing todos."""
    # First, create some initial todos
    initial_todos = [
        {"content": "Task 1", "priority": "medium"},
        {"content": "Task 2", "priority": "high"},
    ]

    # Write the initial todos
    todo_write(mock_context, initial_todos)

    # Read todos to get their IDs
    with open(mock_todo_file, "r") as f:
        saved_todos = json.load(f)

    # Update one todo and add a new one
    updated_todos = [
        {
            "id": saved_todos[0]["id"],
            "content": "Task 1 Updated",
            "status": "in_progress",
        },
        {"content": "Task 3", "priority": "low"},
    ]

    # Write the updates
    update_result = todo_write(mock_context, updated_todos)

    # Check the update result
    assert "Changed" in update_result
    assert "Task 1" in update_result
    assert "Task 1 Updated" in update_result
    assert "Added" in update_result
    assert "Task 3" in update_result

    # Read the updated todos
    read_result = todo_read(mock_context)

    # Check that all expected todos are present
    assert "Task 1 Updated" in read_result
    assert "Task 2" in read_result  # This one was preserved
    assert "Task 3" in read_result

    # The updated task should be in_progress and appear first
    first_line_with_task = next(
        line for line in read_result.split("\n") if "Task" in line
    )
    assert "Task 1 Updated" in first_line_with_task
    assert "[→]" in first_line_with_task


def test_todo_validation(mock_context, mock_todo_file):
    """Test validation of todo input."""
    # Test with invalid status and priority
    invalid_todos = [
        {"content": "Valid Task"},
        {"content": "Invalid Status", "status": "not_a_status"},
        {"content": "Invalid Priority", "priority": "not_a_priority"},
        {"status": "pending"},  # Missing content
    ]

    # Write should still work but log errors and skip invalid todos
    with mock.patch("builtins.print") as mock_print:
        todo_write(mock_context, invalid_todos)

    # Check that error messages were logged
    mock_print.assert_called()

    # Read the todos
    read_result = todo_read(mock_context)

    # Only the valid todo should be present
    assert "Valid Task" in read_result
    assert "Invalid Status" not in read_result
    assert "Invalid Priority" not in read_result

    # Load the saved file directly to check
    with open(mock_todo_file, "r") as f:
        saved_todos = json.load(f)

    # There should be only one valid todo
    assert len(saved_todos) == 1
    assert saved_todos[0]["content"] == "Valid Task"


def test_sort_todos():
    """Test the sorting of todo items."""
    from silica.developer.tools.todos import sort_todos

    # Create todos with different statuses and priorities
    todos = [
        TodoItem(
            id="1",
            content="Low Priority",
            status=TodoStatus.PENDING,
            priority=TodoPriority.LOW,
        ),
        TodoItem(
            id="2",
            content="Completed High",
            status=TodoStatus.COMPLETED,
            priority=TodoPriority.HIGH,
        ),
        TodoItem(
            id="3",
            content="In Progress",
            status=TodoStatus.IN_PROGRESS,
            priority=TodoPriority.MEDIUM,
        ),
        TodoItem(
            id="4",
            content="High Priority",
            status=TodoStatus.PENDING,
            priority=TodoPriority.HIGH,
        ),
    ]

    # Sort the todos
    sorted_todos = sort_todos(todos)

    # Check the order
    assert sorted_todos[0].id == "3"  # In Progress should be first
    assert sorted_todos[1].id == "4"  # High Priority Pending second
    assert sorted_todos[2].id == "1"  # Low Priority Pending third
    assert sorted_todos[3].id == "2"  # Completed last


def test_todo_multiple_sessions(mock_context, tmp_path):
    """Test that todos are isolated by session."""
    # Create two different session IDs
    session_id_1 = str(uuid.uuid4())
    session_id_2 = str(uuid.uuid4())

    # Set up contexts for both sessions
    context_1 = mock.MagicMock(spec=AgentContext)
    context_1.session_id = session_id_1

    context_2 = mock.MagicMock(spec=AgentContext)
    context_2.session_id = session_id_2

    # Create a temporary directory for todos
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()

    # Mock the get_todos_dir function
    with mock.patch(
        "silica.developer.tools.todos.get_todos_dir", return_value=todos_dir
    ):
        # Add a todo for session 1
        todo_write(context_1, [{"content": "Session 1 Task"}])

        # Add a todo for session 2
        todo_write(context_2, [{"content": "Session 2 Task"}])

        # Read todos for both sessions
        result_1 = todo_read(context_1)
        result_2 = todo_read(context_2)

    # Check that each session has its own todos
    assert "Session 1 Task" in result_1
    assert "Session 2 Task" not in result_1

    assert "Session 2 Task" in result_2
    assert "Session 1 Task" not in result_2
