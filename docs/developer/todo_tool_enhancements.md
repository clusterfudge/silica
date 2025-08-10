# Todo Tools Enhancements

This document describes the enhanced todo tools implementation in the Heare developer framework.

## Overview

The todo tools have been redesigned to provide a more intuitive and flexible interface for todo management. The enhancements include:

1. **Denormalized Single-Todo Operations**: Instead of passing complex structured data, the tools now handle one todo at a time with simple parameters.
2. **Machine-Readable Metadata**: The `todo_read` tool now includes a structured metadata section to communicate IDs and properties.
3. **Specialized Tool Functions**: The implementation now provides dedicated tools for specific operations.
4. **Clear Feedback Responses**: Each tool provides explicit feedback about the changes made.
5. **Backward Compatibility**: The original `todo_write` tool is maintained for compatibility.

## New Tools

### `todo_read`

Reads and displays the current todo list with metadata.

```python
todo_read()
```

### `todo_add`

Adds a new todo item.

```python
todo_add(content="Implement feature X", priority="high")
```

### `todo_update`

Updates an existing todo by ID.

```python
todo_update(todo_id="abc123", content="Updated description", priority="medium", status="in_progress")
```

### `todo_complete`

Marks a todo as completed.

```python
todo_complete(todo_id="abc123")
```

### `todo_delete`

Deletes a todo.

```python
todo_delete(todo_id="abc123")
```

## Metadata Format

The `todo_read` tool now includes a machine-readable metadata section in its output, formatted as JSON:

```
# Todo List
[ ] Task 1 (medium)
[→] Task 2 (high)
[✓] Task 3 (low)

## METADATA
```json
{
  "todos": [
    {
      "id": "unique-id-1",
      "content": "Task 1",
      "status": "pending",
      "priority": "medium"
    },
    {
      "id": "unique-id-2",
      "content": "Task 2",
      "status": "in_progress",
      "priority": "high"
    },
    {
      "id": "unique-id-3",
      "content": "Task 3",
      "status": "completed",
      "priority": "low"
    }
  ]
}
```
```

This metadata section allows AI assistants to easily extract the IDs needed for operations on specific todos, while keeping the human-readable output clean and focused on the content.

## Use Cases

### Adding a New Todo

```python
todo_add(content="Implement error handling", priority="high")
```

### Updating a Todo's Status

```python
# First, read todos to get the ID
todos = todo_read()
# Extract ID from metadata
todo_update(todo_id="the-extracted-id", status="in_progress")
```

### Completing Multiple Todos in One Operation

```python
# Extract IDs from todo_read metadata
todo_complete(todo_id="id1")
todo_complete(todo_id="id2")
```

## Backward Compatibility

The original `todo_write` tool is still available and functions as before, maintaining backward compatibility.