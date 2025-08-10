"""
Tools for managing session-based todo lists.

This module provides tools to create, read, update, and delete todos for the current session.
Todos are stored in JSON files in the ~/.local/share/silica/todos directory,
with each session having its own todo file named by session ID.
"""

import json
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from uuid import uuid4

from silica.developer.context import AgentContext
from silica.developer.tools.framework import tool
from silica.developer.utils import get_data_dir, ensure_dir_exists, CustomJSONEncoder


class TodoStatus(str, Enum):
    """Status of a todo item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class TodoPriority(str, Enum):
    """Priority of a todo item."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class TodoItem:
    """A todo item."""

    id: str
    content: str
    status: TodoStatus
    priority: TodoPriority

    @classmethod
    def create(cls, content: str, priority: TodoPriority = TodoPriority.MEDIUM):
        """Create a new todo item with a unique ID."""
        return cls(
            id=str(uuid4()),
            content=content,
            status=TodoStatus.PENDING,
            priority=priority,
        )


def get_todos_dir() -> Path:
    """Get the directory for storing todos."""
    todos_dir = get_data_dir() / "todos"
    ensure_dir_exists(todos_dir)
    return todos_dir


def get_todo_file(session_id: str) -> Path:
    """Get the path to a todo file for a session."""
    return get_todos_dir() / f"{session_id}.json"


def load_todos(session_id: str) -> List[TodoItem]:
    """Load todos from a file."""
    todo_file = get_todo_file(session_id)
    if not todo_file.exists():
        return []

    try:
        with open(todo_file, "r") as f:
            todos_data = json.load(f)

        return [
            TodoItem(
                id=item["id"],
                content=item["content"],
                status=TodoStatus(item["status"]),
                priority=TodoPriority(item["priority"]),
            )
            for item in todos_data
        ]
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        # Log the error but return an empty list to avoid disrupting the user
        print(f"Error loading todos: {e}")
        return []


def save_todos(session_id: str, todos: List[TodoItem]) -> None:
    """Save todos to a file."""
    todo_file = get_todo_file(session_id)

    todos_data = [
        {
            "id": todo.id,
            "content": todo.content,
            "status": todo.status,
            "priority": todo.priority,
        }
        for todo in todos
    ]

    with open(todo_file, "w") as f:
        json.dump(todos_data, f, cls=CustomJSONEncoder, indent=2)


def sort_todos(todos: List[TodoItem]) -> List[TodoItem]:
    """Sort todos by status (in_progress first) then priority."""
    # Define the order of statuses for sorting
    status_order = {
        TodoStatus.IN_PROGRESS: 0,
        TodoStatus.PENDING: 1,
        TodoStatus.COMPLETED: 2,
    }

    # Define the order of priorities for sorting
    priority_order = {TodoPriority.HIGH: 0, TodoPriority.MEDIUM: 1, TodoPriority.LOW: 2}

    return sorted(
        todos,
        key=lambda todo: (status_order[todo.status], priority_order[todo.priority]),
    )


def format_todo_list(todos: List[TodoItem], include_metadata: bool = True) -> str:
    """
    Format a list of todos for display.

    Args:
        todos: List of todo items to format
        include_metadata: Whether to include machine-readable metadata
    """
    if not todos:
        result = "No todos in the current session."
        if include_metadata:
            result += '\n\n## METADATA\n```json\n{"todos": []}\n```'
        return result

    sorted_todos = sort_todos(todos)

    # Format with status indicators and priorities
    lines = ["# Todo List", ""]

    for todo in sorted_todos:
        status_indicator = {
            TodoStatus.PENDING: "[ ]",
            TodoStatus.IN_PROGRESS: "[→]",
            TodoStatus.COMPLETED: "[✓]",
        }[todo.status]

        priority_indicator = {
            TodoPriority.HIGH: "(high)",
            TodoPriority.MEDIUM: "(medium)",
            TodoPriority.LOW: "(low)",
        }[todo.priority]

        lines.append(f"{status_indicator} {todo.content} {priority_indicator}")

    result = "\n".join(lines)

    # Add machine-readable metadata if requested
    if include_metadata:
        metadata = {
            "todos": [
                {
                    "id": todo.id,
                    "content": todo.content,
                    "status": todo.status,
                    "priority": todo.priority,
                }
                for todo in sorted_todos
            ]
        }
        result += f"\n\n## METADATA\n```json\n{json.dumps(metadata, cls=CustomJSONEncoder, indent=2)}\n```"

    return result


def format_todo_diff(old_todos: List[TodoItem], new_todos: List[TodoItem]) -> str:
    """Format the difference between two todo lists."""
    # Create dictionaries for easier comparison
    old_dict = {todo.id: todo for todo in old_todos}
    new_dict = {todo.id: todo for todo in new_todos}

    added = [todo for todo in new_todos if todo.id not in old_dict]
    removed = [todo for todo in old_todos if todo.id not in new_dict]
    changed = [
        (old_dict[todo_id], new_dict[todo_id])
        for todo_id in set(old_dict) & set(new_dict)
        if old_dict[todo_id].status != new_dict[todo_id].status
        or old_dict[todo_id].priority != new_dict[todo_id].priority
        or old_dict[todo_id].content != new_dict[todo_id].content
    ]

    if not (added or removed or changed):
        return "No changes to the todo list."

    lines = ["# Todo List Changes", ""]

    if added:
        lines.append("## Added")
        for todo in added:
            lines.append(f"+ {todo.content} ({todo.priority})")
        lines.append("")

    if removed:
        lines.append("## Removed")
        for todo in removed:
            lines.append(f"- {todo.content}")
        lines.append("")

    if changed:
        lines.append("## Changed")
        for old, new in changed:
            if old.content != new.content:
                lines.append(f"* Changed: '{old.content}' → '{new.content}'")
            if old.status != new.status:
                lines.append(
                    f"* Status: '{old.status}' → '{new.status}' for '{new.content}'"
                )
            if old.priority != new.priority:
                lines.append(
                    f"* Priority: '{old.priority}' → '{new.priority}' for '{new.content}'"
                )
        lines.append("")

    return "\n".join(lines)


def get_todo_by_id(todos: List[TodoItem], todo_id: str) -> Optional[TodoItem]:
    """Find a todo by its ID."""
    for todo in todos:
        if todo.id == todo_id:
            return todo
    return None


def validate_priority(priority_str: str) -> TodoPriority:
    """Validate and convert priority string to TodoPriority."""
    priority_str = priority_str.lower()
    if priority_str not in [p.value for p in TodoPriority]:
        raise ValueError(
            f"Invalid priority: {priority_str}. Valid values are: high, medium, low"
        )
    return TodoPriority(priority_str)


@tool
def todo_read(context: AgentContext) -> str:
    """
    Read the current todo list for the session.

    Returns a formatted list of todos for the current session,
    including a machine-readable METADATA section with todo IDs
    and other properties needed for operations on specific todos.
    """
    todos = load_todos(context.session_id)
    return format_todo_list(todos)


@tool
def todo_add(context: AgentContext, content: str, priority: str = "medium") -> str:
    """
    Add a new todo item to the current session.

    Args:
        content: The content or description of the todo
        priority: The priority level (high, medium, low)

    Returns a confirmation message and the updated todo list.
    """
    try:
        # Validate priority
        todo_priority = validate_priority(priority)

        # Load existing todos
        todos = load_todos(context.session_id)

        # Create new todo
        new_todo = TodoItem.create(content=content, priority=todo_priority)

        # Add to list and save
        todos.append(new_todo)
        save_todos(context.session_id, todos)

        return f"✅ Added todo: '{content}' with {priority} priority\n\n{format_todo_list(todos)}"
    except ValueError as e:
        return f"❌ Error adding todo: {str(e)}"


@tool
def todo_update(
    context: AgentContext,
    todo_id: str,
    content: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
) -> str:
    """
    Update an existing todo item by ID.

    Args:
        todo_id: The ID of the todo to update
        content: New content for the todo (optional)
        priority: New priority level (high, medium, low) (optional)
        status: New status (pending, in_progress, completed) (optional)

    Returns a confirmation message and the updated todo list.
    """
    try:
        # Load existing todos
        todos = load_todos(context.session_id)

        # Find the todo by ID
        todo = get_todo_by_id(todos, todo_id)
        if not todo:
            return f"❌ Error: Todo with ID '{todo_id}' not found"

        # Track what changed
        changes = []

        # Update content if provided
        if content is not None and content != todo.content:
            old_content = todo.content
            todo.content = content
            changes.append(f"content: '{old_content}' → '{content}'")

        # Update priority if provided
        if priority is not None:
            try:
                new_priority = validate_priority(priority)
                if new_priority != todo.priority:
                    old_priority = todo.priority.value
                    todo.priority = new_priority
                    changes.append(
                        f"priority: '{old_priority}' → '{new_priority.value}'"
                    )
            except ValueError as e:
                return f"❌ Error updating todo: {str(e)}"

        # Update status if provided
        if status is not None:
            status = status.lower()
            if status not in [s.value for s in TodoStatus]:
                return f"❌ Error: Invalid status '{status}'. Valid values are: pending, in_progress, completed"

            new_status = TodoStatus(status)
            if new_status != todo.status:
                old_status = todo.status.value
                todo.status = new_status
                changes.append(f"status: '{old_status}' → '{new_status.value}'")

        # Save changes
        if changes:
            save_todos(context.session_id, todos)
            changes_text = ", ".join(changes)
            return f"✅ Updated todo: '{todo.content}' ({changes_text})\n\n{format_todo_list(todos)}"
        else:
            return "ℹ️ No changes made to the todo"
    except Exception as e:
        return f"❌ Error updating todo: {str(e)}"


@tool
def todo_complete(context: AgentContext, todo_id: str) -> str:
    """
    Mark a todo item as completed.

    Args:
        todo_id: The ID of the todo to mark as completed

    Returns a confirmation message and the updated todo list.
    """
    try:
        # Load existing todos
        todos = load_todos(context.session_id)

        # Find the todo by ID
        todo = get_todo_by_id(todos, todo_id)
        if not todo:
            return f"❌ Error: Todo with ID '{todo_id}' not found"

        # Mark as completed if not already
        if todo.status == TodoStatus.COMPLETED:
            return f"ℹ️ Todo '{todo.content}' is already marked as completed"

        # Update status
        old_status = todo.status.value
        todo.status = TodoStatus.COMPLETED

        # Save changes
        save_todos(context.session_id, todos)

        return f"✅ Marked todo as completed: '{todo.content}' (status: '{old_status}' → 'completed')\n\n{format_todo_list(todos)}"
    except Exception as e:
        return f"❌ Error completing todo: {str(e)}"


@tool
def todo_delete(context: AgentContext, todo_id: str) -> str:
    """
    Delete a todo item.

    Args:
        todo_id: The ID of the todo to delete

    Returns a confirmation message and the updated todo list.
    """
    try:
        # Load existing todos
        todos = load_todos(context.session_id)

        # Find the todo by ID
        todo = get_todo_by_id(todos, todo_id)
        if not todo:
            return f"❌ Error: Todo with ID '{todo_id}' not found"

        # Remove the todo
        content = todo.content
        todos = [t for t in todos if t.id != todo_id]

        # Save changes
        save_todos(context.session_id, todos)

        return f"✅ Deleted todo: '{content}'\n\n{format_todo_list(todos)}"
    except Exception as e:
        return f"❌ Error deleting todo: {str(e)}"


# Keep the original todo_write tool for backward compatibility
@tool
def todo_write(context: AgentContext, todos: List[Dict[str, Any]]) -> str:
    """
    Create or update todos in the current session.

    Args:
        todos: A list of todo items. Each item must have a "content" field and may also have
              "status" (pending, in_progress, completed), "priority" (high, medium, low),
              and "id" (to update an existing todo).

    Returns a summary of changes made to the todo list.
    """
    # assume that we're potentially getting garbage data from the model (json as a string)
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError:
            return "Tool invocation not well formed. 😩"

    # Load existing todos
    old_todos = load_todos(context.session_id)

    # Validate and convert input
    new_todos = []
    for item in todos:
        try:
            # Ensure required fields exist
            if "content" not in item:
                print("Error validating todo item: Missing required field 'content'")
                continue

            # Use existing ID or create new one
            todo_id = item.get("id", str(uuid4()))

            # Parse status
            status_str = item.get("status", "pending").lower()
            if status_str not in [s.value for s in TodoStatus]:
                print(f"Error validating todo item: Invalid status '{status_str}'")
                continue
            status = TodoStatus(status_str)

            # Parse priority
            priority_str = item.get("priority", "medium").lower()
            if priority_str not in [p.value for p in TodoPriority]:
                print(f"Error validating todo item: Invalid priority '{priority_str}'")
                continue
            priority = TodoPriority(priority_str)

            # Create TodoItem
            new_todos.append(
                TodoItem(
                    id=todo_id,
                    content=item["content"],
                    status=status,
                    priority=priority,
                )
            )
        except (ValueError, KeyError) as e:
            # Log the error but continue processing other items
            print(f"Error validating todo item: {e}")

    # Get existing todo IDs
    {todo.id for todo in old_todos}
    update_ids = {todo.id for todo in new_todos}

    # Add preserved todos (those not in the update but have IDs that exist)
    preserved_todos = [todo for todo in old_todos if todo.id not in update_ids]
    final_todos = preserved_todos + new_todos

    # Save the updated list
    save_todos(context.session_id, final_todos)

    # Return a diff showing what changed
    return format_todo_diff(old_todos, final_todos)
