"""Shared helpers for sync CLI commands.

This module provides common utilities for memory-sync and history-sync CLI commands,
including the dry-run display logic.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from silica.developer.memory.sync import SyncPlan


def display_sync_plan(console: Console, plan: SyncPlan, context: str = "") -> None:
    """Display a sync plan in a user-friendly format.

    Shows summary counts and details of each operation type.

    Args:
        console: Rich console for output
        plan: The sync plan to display
        context: Optional context string (e.g., "persona 'default'" or "session 'abc123'")
    """
    # Summary header
    if context:
        console.print(f"\n[bold]Sync Plan for {context}:[/bold]\n")
    else:
        console.print("\n[bold]Sync Plan:[/bold]\n")

    # Create summary table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Operation", style="cyan", no_wrap=True)
    table.add_column("Count", justify="right", style="white")

    table.add_row("Uploads", str(len(plan.upload)))
    table.add_row("Downloads", str(len(plan.download)))
    table.add_row("Delete local", str(len(plan.delete_local)))
    table.add_row("Delete remote", str(len(plan.delete_remote)))
    table.add_row("Conflicts", str(len(plan.conflicts)))
    table.add_row(
        "[bold]Total operations[/bold]", f"[bold]{plan.total_operations}[/bold]"
    )

    console.print(table)

    # Check if no operations needed
    if plan.total_operations == 0 and not plan.conflicts:
        console.print(
            Panel(
                "[green]✓ Everything is in sync. No operations needed.[/green]",
                border_style="green",
            )
        )
        return

    # Show details for each operation type
    _display_operation_details(
        console,
        plan.upload,
        title="Files to upload",
        style="cyan",
        icon="↑",
    )

    _display_operation_details(
        console,
        plan.download,
        title="Files to download",
        style="cyan",
        icon="↓",
    )

    _display_operation_details(
        console,
        plan.delete_local,
        title="Files to delete locally",
        style="yellow",
        icon="✗",
    )

    _display_operation_details(
        console,
        plan.delete_remote,
        title="Files to delete remotely",
        style="yellow",
        icon="✗",
    )

    _display_operation_details(
        console,
        plan.conflicts,
        title="Conflicts requiring resolution",
        style="red",
        icon="⚠",
        show_reason=True,
    )

    # Footer with next steps
    console.print()
    if plan.conflicts:
        console.print(
            "[yellow]Note: Conflicts will be resolved via LLM merge during actual sync.[/yellow]"
        )
    console.print("[dim]Run without --dry-run to execute these operations.[/dim]")


def _display_operation_details(
    console: Console,
    operations: list,
    title: str,
    style: str = "white",
    icon: str = "•",
    max_display: int = 10,
    show_reason: bool = False,
) -> None:
    """Display details for a list of sync operations.

    Args:
        console: Rich console for output
        operations: List of SyncOperationDetail objects
        title: Section title
        style: Rich style for the title
        icon: Icon to show before each item
        max_display: Maximum number of items to display
        show_reason: Whether to show the reason for each operation
    """
    if not operations:
        return

    console.print(f"\n[bold {style}]{title}:[/bold {style}]")

    for op in operations[:max_display]:
        if show_reason and op.reason:
            console.print(f"  {icon} {op.path}")
            console.print(f"    [dim]{op.reason}[/dim]")
        else:
            # Include size info if available
            size_info = ""
            if op.local_size:
                size_info = f" ({_format_size(op.local_size)})"
            elif op.remote_size:
                size_info = f" ({_format_size(op.remote_size)})"
            console.print(f"  {icon} {op.path}{size_info}")

    if len(operations) > max_display:
        remaining = len(operations) - max_display
        console.print(f"  [dim]... and {remaining} more[/dim]")


def _format_size(size_bytes: int) -> str:
    """Format a size in bytes to a human-readable string.

    Args:
        size_bytes: Size in bytes

    Returns:
        Human-readable size string
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
