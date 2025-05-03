"""Todos command for silica."""

import click
import datetime
from rich.console import Console
from rich.table import Table

from silica.config import get_silica_dir, find_git_root

console = Console()


@click.group(name="todos")
def todos():
    """Manage todos for the agent."""


@todos.command()
def list():
    """List all todos for the agent."""
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    silica_dir = get_silica_dir()
    if not silica_dir or not (silica_dir / "config.yaml").exists():
        console.print(
            "[red]Error: No silica environment found in this repository.[/red]"
        )
        console.print("Run [bold]silica create[/bold] to set up an environment first.")
        return

    todo_file = silica_dir / "todos.yaml"
    if not todo_file.exists():
        console.print("[yellow]No todos found.[/yellow]")
        return

    import yaml

    with open(todo_file, "r") as f:
        todos_data = yaml.safe_load(f) or {}

    todos_list = todos_data.get("todos", [])

    if not todos_list:
        console.print("[yellow]No todos found.[/yellow]")
        return

    table = Table(title="Agent Todos")
    table.add_column("ID", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Status", style="green")

    for idx, todo in enumerate(todos_list):
        status = todo.get("status", "pending")
        status_style = {
            "pending": "yellow",
            "in_progress": "blue",
            "completed": "green",
            "failed": "red",
        }.get(status, "white")

        table.add_row(
            str(idx + 1),
            todo.get("description", "No description"),
            f"[{status_style}]{status}[/{status_style}]",
        )

    console.print(table)


@todos.command()
@click.argument("description")
def add(description):
    """Add a new todo."""
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    silica_dir = get_silica_dir()
    if not silica_dir or not (silica_dir / "config.yaml").exists():
        console.print(
            "[red]Error: No silica environment found in this repository.[/red]"
        )
        console.print("Run [bold]silica create[/bold] to set up an environment first.")
        return

    todo_file = silica_dir / "todos.yaml"

    import yaml

    todos_data = {}
    if todo_file.exists():
        with open(todo_file, "r") as f:
            todos_data = yaml.safe_load(f) or {}

    todos_list = todos_data.get("todos", [])

    # Add new todo
    new_todo = {
        "description": description,
        "status": "pending",
        "created_at": str(datetime.datetime.now()),
    }

    todos_list.append(new_todo)
    todos_data["todos"] = todos_list

    with open(todo_file, "w") as f:
        yaml.dump(todos_data, f)

    console.print(f"[green]Added todo: {description}[/green]")


@todos.command()
@click.argument("todo_id", type=int)
@click.argument(
    "status", type=click.Choice(["pending", "in_progress", "completed", "failed"])
)
def update(todo_id, status):
    """Update the status of a todo."""
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    silica_dir = get_silica_dir()
    if not silica_dir or not (silica_dir / "config.yaml").exists():
        console.print(
            "[red]Error: No silica environment found in this repository.[/red]"
        )
        console.print("Run [bold]silica create[/bold] to set up an environment first.")
        return

    todo_file = silica_dir / "todos.yaml"

    if not todo_file.exists():
        console.print("[red]No todos found.[/red]")
        return

    import yaml

    with open(todo_file, "r") as f:
        todos_data = yaml.safe_load(f) or {}

    todos_list = todos_data.get("todos", [])

    if not todos_list or todo_id <= 0 or todo_id > len(todos_list):
        console.print(f"[red]Todo with ID {todo_id} not found.[/red]")
        return

    # Update todo status
    todos_list[todo_id - 1]["status"] = status
    todos_data["todos"] = todos_list

    with open(todo_file, "w") as f:
        yaml.dump(todos_data, f)

    console.print(f"[green]Updated todo {todo_id} status to {status}[/green]")


@todos.command()
@click.argument("todo_id", type=int)
def remove(todo_id):
    """Remove a todo."""
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    silica_dir = get_silica_dir()
    if not silica_dir or not (silica_dir / "config.yaml").exists():
        console.print(
            "[red]Error: No silica environment found in this repository.[/red]"
        )
        console.print("Run [bold]silica create[/bold] to set up an environment first.")
        return

    todo_file = silica_dir / "todos.yaml"

    if not todo_file.exists():
        console.print("[red]No todos found.[/red]")
        return

    import yaml

    with open(todo_file, "r") as f:
        todos_data = yaml.safe_load(f) or {}

    todos_list = todos_data.get("todos", [])

    if not todos_list or todo_id <= 0 or todo_id > len(todos_list):
        console.print(f"[red]Todo with ID {todo_id} not found.[/red]")
        return

    # Remove todo
    removed_todo = todos_list.pop(todo_id - 1)
    todos_data["todos"] = todos_list

    with open(todo_file, "w") as f:
        yaml.dump(todos_data, f)

    console.print(f"[green]Removed todo: {removed_todo.get('description')}[/green]")
