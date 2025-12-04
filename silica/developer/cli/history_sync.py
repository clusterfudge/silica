"""CLI commands for history sync.

This module provides commands for syncing conversation history per session.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import cyclopts
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from silica.developer.memory.proxy_config import MemoryProxyConfig
from silica.developer.memory.proxy_client import MemoryProxyClient
from silica.developer.memory.sync import SyncEngine
from silica.developer.memory.sync_config import SyncConfig
from silica.developer.memory.sync_coordinator import sync_with_retry
from silica.developer.memory.llm_conflict_resolver import LLMConflictResolver
from silica.developer import personas


@dataclass
class SessionSyncResult:
    """Result of syncing a single session."""

    session_id: str
    succeeded: int = 0
    failed: int = 0
    conflicts: int = 0
    skipped: int = 0
    duration: float = 0.0
    error: str | None = None
    status: str = "pending"  # pending, syncing, done, error


# Create the history-sync command group
history_sync_app = cyclopts.App(
    name="history-sync", help="Manage conversation history synchronization"
)


def _get_console() -> Console:
    """Get a Rich console for output."""
    return Console()


def _get_persona_directory(persona_name: str | None = None) -> tuple[Path, str]:
    """Get the persona directory and name.

    Args:
        persona_name: Optional persona name. If None, uses 'default'.

    Returns:
        Tuple of (persona_directory, persona_name)
    """
    if not persona_name:
        persona_name = "default"

    persona_obj = personas.get_or_create(persona_name, interactive=False)
    return persona_obj.base_directory, persona_name


def _list_sessions(persona_dir: Path) -> list[dict]:
    """List all available sessions for a persona.

    Args:
        persona_dir: Persona base directory

    Returns:
        List of session info dicts with keys: session_id, path, file_count, has_index
    """
    history_dir = persona_dir / "history"
    if not history_dir.exists():
        return []

    sessions = []
    for session_path in sorted(history_dir.iterdir()):
        if session_path.is_dir():
            # Count files (excluding sync metadata)
            files = [
                f
                for f in session_path.iterdir()
                if f.is_file()
                and not f.name.startswith(".sync-")
                and f.suffix in [".md", ".json"]
            ]

            sessions.append(
                {
                    "session_id": session_path.name,
                    "path": session_path,
                    "file_count": len(files),
                    "has_index": (session_path / ".sync-index-history.json").exists(),
                }
            )

    return sessions


@history_sync_app.command
def list(
    *,
    persona: Annotated[
        Optional[str], cyclopts.Parameter(help="Persona to list sessions for")
    ] = None,
):
    """List all conversation history sessions.

    Shows available sessions with their sync status and file counts.

    Example:
        silica history-sync list
        silica history-sync list --persona autonomous_engineer
    """
    console = _get_console()

    try:
        persona_dir, persona_name = _get_persona_directory(persona)

        # Get sessions
        sessions = _list_sessions(persona_dir)

        if not sessions:
            console.print(
                f"[yellow]No history sessions found for persona '{persona_name}'[/yellow]"
            )
            return

        # Create table
        table = Table(
            title=f"History Sessions for '{persona_name}'",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Session ID", style="white")
        table.add_column("Files", justify="right", style="cyan")
        table.add_column("Sync Status", style="white")

        for session in sessions:
            sync_status = "✓ Synced" if session["has_index"] else "○ Not synced"
            table.add_row(
                session["session_id"],
                str(session["file_count"]),
                sync_status,
            )

        console.print(table)
        console.print(f"\n[dim]Total: {len(sessions)} session(s)[/dim]")
        console.print(
            "[dim]To sync a session: silica history-sync sync --session <id>[/dim]"
        )

    except Exception as e:
        console.print(f"[red]Error listing sessions: {e}[/red]")
        raise


@history_sync_app.command
def status(
    *,
    session: Annotated[str, cyclopts.Parameter(help="Session ID to check status for")],
    persona: Annotated[Optional[str], cyclopts.Parameter(help="Persona name")] = None,
):
    """Show sync status for a specific session.

    Displays configuration, sync state, and pending operations for a session.

    Example:
        silica history-sync status --session session-123
        silica history-sync status --session session-123 --persona autonomous_engineer
    """
    console = _get_console()

    try:
        config = MemoryProxyConfig()
        persona_dir, persona_name = _get_persona_directory(persona)

        session_dir = persona_dir / "history" / session
        if not session_dir.exists():
            console.print(f"[red]Error: Session '{session}' not found[/red]")
            return

        # Create status table
        table = Table(
            title=f"History Sync Status: {session}", show_header=False, box=None
        )
        table.add_column("Key", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")

        # Configuration status
        table.add_row("Configured", "✓ Yes" if config.is_configured else "✗ No")

        if config.is_configured:
            table.add_row("Remote URL", config.remote_url)
            table.add_row("Persona", persona_name)
            table.add_row("Session", session)

            # Check if session has been synced
            index_file = session_dir / ".sync-index-history.json"
            has_synced = index_file.exists()
            table.add_row("Ever Synced", "✓ Yes" if has_synced else "✗ No")

            # Count files
            files = [
                f
                for f in session_dir.iterdir()
                if f.is_file()
                and not f.name.startswith(".sync-")
                and f.suffix in [".md", ".json"]
            ]
            table.add_row("Local Files", str(len(files)))

            # Show validation errors if any
            is_valid, errors = config.validate()
            if not is_valid:
                table.add_row("Validation", "[red]✗ Failed[/red]")
                for error in errors:
                    table.add_row("", f"  • {error}")
            else:
                table.add_row("Validation", "✓ Passed")
        else:
            table.add_row(
                "", "[yellow]Run 'silica memory-sync setup' to configure[/yellow]"
            )

        console.print(table)

        # Show next steps
        if config.is_configured:
            console.print(
                f"\n[dim]To sync this session: silica history-sync sync --session {session}[/dim]"
            )

    except Exception as e:
        console.print(f"[red]Error getting status: {e}[/red]")
        raise


@dataclass
class SessionPlanResult:
    """Result of analyzing a single session's sync plan."""

    session_id: str
    uploads: int = 0
    downloads: int = 0
    delete_local: int = 0
    delete_remote: int = 0
    conflicts: int = 0
    total_ops: int = 0
    error: str | None = None


def _analyze_session_plan(
    config: MemoryProxyConfig,
    persona_name: str,
    session: str,
) -> SessionPlanResult:
    """Analyze sync plan for a single session without displaying.

    Args:
        config: Memory proxy configuration
        persona_name: Name of the persona
        session: Session ID

    Returns:
        SessionPlanResult with plan summary
    """
    result = SessionPlanResult(session_id=session)

    try:
        # Create proxy client
        client = MemoryProxyClient(base_url=config.remote_url, token=config.auth_token)

        # Create sync configuration for this session
        sync_config = SyncConfig.for_history(persona_name, session)

        # Create sync engine (no conflict resolver needed for analysis)
        sync_engine = SyncEngine(
            client=client,
            config=sync_config,
            conflict_resolver=None,
        )

        # Analyze what would be synced
        plan = sync_engine.analyze_sync_operations()

        result.uploads = len(plan.upload)
        result.downloads = len(plan.download)
        result.delete_local = len(plan.delete_local)
        result.delete_remote = len(plan.delete_remote)
        result.conflicts = len(plan.conflicts)
        result.total_ops = plan.total_operations

        return result

    except Exception as e:
        result.error = str(e)
        return result


def _sync_single_session(
    console: Console,
    config: MemoryProxyConfig,
    persona_name: str,
    session: str,
    session_dir: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> SessionSyncResult:
    """Sync a single session.

    Args:
        console: Rich console for output
        config: Memory proxy configuration
        persona_name: Name of the persona
        session: Session ID
        session_dir: Path to the session directory
        dry_run: If True, only analyze without executing
        verbose: If True and dry_run, show detailed plan

    Returns:
        SessionSyncResult with sync outcome
    """
    from silica.developer.cli.sync_helpers import display_sync_plan

    result_info = SessionSyncResult(session_id=session)

    try:
        # Get Anthropic API key for LLM conflict resolution
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

        # Create conflict resolver if we have an API key
        conflict_resolver = None
        if anthropic_key:
            from anthropic import Anthropic

            anthropic_client = Anthropic(api_key=anthropic_key)
            conflict_resolver = LLMConflictResolver(client=anthropic_client)

        # Create proxy client
        client = MemoryProxyClient(base_url=config.remote_url, token=config.auth_token)

        # Create sync configuration for this session
        sync_config = SyncConfig.for_history(persona_name, session)

        # Create sync engine
        sync_engine = SyncEngine(
            client=client,
            config=sync_config,
            conflict_resolver=conflict_resolver,
        )

        if dry_run:
            # Analyze what would be synced
            plan = sync_engine.analyze_sync_operations()
            if verbose:
                display_sync_plan(console, plan, context=f"session '{session}'")
            result_info.succeeded = plan.total_operations
            result_info.conflicts = len(plan.conflicts)
            result_info.status = "done"
            return result_info

        # Perform sync with retry and automatic conflict resolution
        result = sync_with_retry(
            sync_engine=sync_engine, max_retries=3, show_progress=False
        )

        result_info.succeeded = len(result.succeeded)
        result_info.failed = len(result.failed)
        result_info.conflicts = len(result.conflicts)
        result_info.skipped = len(result.skipped)
        result_info.duration = result.duration
        result_info.status = "done" if not result.failed else "error"

        return result_info

    except Exception as e:
        result_info.error = str(e)
        result_info.status = "error"
        return result_info


def _sync_all_sessions_with_progress(
    console: Console,
    config: MemoryProxyConfig,
    persona_name: str,
    sessions_to_sync: list[dict],
) -> list[SessionSyncResult]:
    """Sync multiple sessions with a live progress display.

    Args:
        console: Rich console for output
        config: Memory proxy configuration
        persona_name: Name of the persona
        sessions_to_sync: List of session info dicts

    Returns:
        List of SessionSyncResult for each session
    """
    results: list[SessionSyncResult] = []

    # Create progress display
    overall_progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Overall Progress"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
    )

    session_progress = Progress(
        TextColumn("  "),
        TextColumn("{task.fields[status_icon]}"),
        TextColumn("[bold]{task.fields[session_id]:<40}"),
        TextColumn("{task.fields[status_text]}"),
    )

    # Create a group to show both progress displays
    progress_group = Group(
        Panel(
            Group(overall_progress, session_progress),
            title=f"[bold]Syncing {len(sessions_to_sync)} Sessions[/bold]",
            border_style="blue",
        )
    )

    # Add overall task
    overall_task = overall_progress.add_task("Syncing...", total=len(sessions_to_sync))

    # Add a summary row for skipped (in-sync) sessions - starts hidden
    skipped_count = 0
    skipped_task = session_progress.add_task(
        "skipped",
        status_icon="[dim]○[/dim]",
        session_id="",
        status_text="",
        visible=False,
    )

    # Add task for each session
    session_tasks = {}
    for session_info in sessions_to_sync:
        session_id = session_info["session_id"]
        task_id = session_progress.add_task(
            session_id,
            status_icon="○",
            session_id=session_id,
            status_text="[dim]Pending[/dim]",
        )
        session_tasks[session_id] = task_id

    with Live(progress_group, console=console, refresh_per_second=10):
        for session_info in sessions_to_sync:
            session_id = session_info["session_id"]
            session_path = session_info["path"]
            task_id = session_tasks[session_id]

            # Update status to syncing
            session_progress.update(
                task_id,
                status_icon="◐",
                status_text="[cyan]Syncing...[/cyan]",
            )

            # Perform sync
            result = _sync_single_session(
                console=console,
                config=config,
                persona_name=persona_name,
                session=session_id,
                session_dir=session_path,
                dry_run=False,
            )
            results.append(result)

            # Update status based on result
            if result.error:
                session_progress.update(
                    task_id,
                    status_icon="[red]✗[/red]",
                    status_text=f"[red]Error: {result.error[:30]}...[/red]"
                    if len(result.error) > 30
                    else f"[red]Error: {result.error}[/red]",
                )
            elif result.failed > 0:
                session_progress.update(
                    task_id,
                    status_icon="[yellow]⚠[/yellow]",
                    status_text=f"[yellow]{result.succeeded} ok, {result.failed} failed[/yellow]",
                )
            else:
                if result.succeeded > 0:
                    # Show sessions that had actual operations
                    session_progress.update(
                        task_id,
                        status_icon="[green]✓[/green]",
                        status_text=f"[green]{result.succeeded} ops[/green] [dim]({result.duration:.1f}s)[/dim]",
                    )
                else:
                    # Hide sessions that were already in sync and update counter
                    session_progress.update(task_id, visible=False)
                    skipped_count += 1
                    session_progress.update(
                        skipped_task,
                        visible=True,
                        status_icon="[dim]─[/dim]",
                        session_id=f"[dim]({skipped_count} session(s) already in sync)[/dim]",
                        status_text="",
                    )

            # Update overall progress
            overall_progress.update(overall_task, advance=1)

    return results


def _display_dry_run_summary(
    console: Console,
    plans: list[SessionPlanResult],
) -> None:
    """Display a summary table for dry-run analysis.

    Args:
        console: Rich console for output
        plans: List of session plan results
    """
    # Calculate totals
    total_uploads = sum(p.uploads for p in plans)
    total_downloads = sum(p.downloads for p in plans)
    total_delete_local = sum(p.delete_local for p in plans)
    total_delete_remote = sum(p.delete_remote for p in plans)
    total_conflicts = sum(p.conflicts for p in plans)
    total_ops = sum(p.total_ops for p in plans)
    errors = [p for p in plans if p.error]

    # Create table
    table = Table(
        title="Dry Run Summary",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Session", style="white")
    table.add_column("↑ Upload", justify="right", style="green")
    table.add_column("↓ Download", justify="right", style="blue")
    table.add_column("✗ Delete", justify="right", style="yellow")
    table.add_column("⚠ Conflicts", justify="right", style="red")
    table.add_column("Total", justify="right", style="white bold")

    # Count sessions in sync (no operations or conflicts)
    in_sync_count = sum(
        1 for p in plans if not p.error and p.total_ops == 0 and p.conflicts == 0
    )

    for plan in plans:
        if plan.error:
            table.add_row(
                plan.session_id,
                "[red]Error[/red]",
                "",
                "",
                "",
                f"[red]{plan.error[:20]}...[/red]"
                if len(plan.error) > 20
                else f"[red]{plan.error}[/red]",
            )
        elif plan.total_ops > 0 or plan.conflicts > 0:
            # Show sessions that have operations or conflicts
            deletes = plan.delete_local + plan.delete_remote
            table.add_row(
                plan.session_id,
                str(plan.uploads) if plan.uploads else "-",
                str(plan.downloads) if plan.downloads else "-",
                str(deletes) if deletes else "-",
                str(plan.conflicts) if plan.conflicts else "-",
                str(plan.total_ops) if plan.total_ops else "-",
            )
        # Skip sessions that are already in sync (no output row)

    # Add totals row
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{total_uploads}[/bold]",
        f"[bold]{total_downloads}[/bold]",
        f"[bold]{total_delete_local + total_delete_remote}[/bold]",
        f"[bold]{total_conflicts}[/bold]",
        f"[bold]{total_ops}[/bold]",
        style="on dark_blue" if total_ops > 0 else None,
    )

    console.print(table)

    # Show summary message
    if in_sync_count > 0:
        console.print(
            f"\n[dim]({in_sync_count} session(s) already in sync, not shown)[/dim]"
        )

    if total_ops == 0 and total_conflicts == 0 and not errors:
        console.print(
            "[green]✓ All sessions are in sync. No operations needed.[/green]"
        )
    else:
        if total_conflicts > 0:
            console.print(
                f"\n[yellow]Note: {total_conflicts} conflict(s) will be resolved via LLM merge during actual sync.[/yellow]"
            )
        if total_ops > 0 or total_conflicts > 0:
            console.print(
                "[dim]Run without --dry-run to execute these operations.[/dim]"
            )

    if errors:
        console.print(f"\n[red]⚠ {len(errors)} session(s) failed to analyze.[/red]")


@history_sync_app.command
def sync(
    *,
    session: Annotated[
        Optional[str], cyclopts.Parameter(help="Session ID to sync (omit to sync all)")
    ] = None,
    persona: Annotated[Optional[str], cyclopts.Parameter(help="Persona name")] = None,
    dry_run: Annotated[
        bool, cyclopts.Parameter(help="Show plan without executing")
    ] = False,
    verbose: Annotated[
        bool,
        cyclopts.Parameter(help="Show detailed plan for each session (with --dry-run)"),
    ] = False,
):
    """Sync conversation history for sessions.

    If --session is specified, syncs only that session.
    If --session is omitted, syncs ALL sessions for the persona.

    Performs bi-directional sync between local session history and remote storage.
    Uses automatic conflict resolution via LLM when needed.

    Example:
        silica history-sync sync                              # Sync all sessions
        silica history-sync sync --session session-123        # Sync specific session
        silica history-sync sync --dry-run                    # Preview all sessions (summary)
        silica history-sync sync --dry-run --verbose          # Preview with detailed plans
        silica history-sync sync --persona autonomous_engineer
    """
    console = _get_console()

    try:
        config = MemoryProxyConfig()
        persona_dir, persona_name = _get_persona_directory(persona)

        # Check configuration
        if not config.is_configured:
            console.print(
                "[red]Error: Memory proxy not configured. Run 'silica memory-sync setup' first.[/red]"
            )
            return

        # Get Anthropic API key warning (only for actual sync, not dry-run)
        if not dry_run:
            anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
            if not anthropic_key:
                console.print(
                    "[yellow]Warning: ANTHROPIC_API_KEY not set. Conflict resolution will fail if conflicts occur.[/yellow]"
                )

        # Determine which sessions to sync
        if session:
            # Single session mode
            session_dir = persona_dir / "history" / session
            if not session_dir.exists():
                console.print(f"[red]Error: Session '{session}' not found[/red]")
                return
            sessions_to_sync = [{"session_id": session, "path": session_dir}]
        else:
            # All sessions mode
            sessions_to_sync = _list_sessions(persona_dir)
            if not sessions_to_sync:
                console.print(
                    f"[yellow]No history sessions found for persona '{persona_name}'[/yellow]"
                )
                return

        # Handle dry-run mode
        if dry_run:
            console.print(
                f"[cyan]Analyzing sync plan for {len(sessions_to_sync)} session(s)...[/cyan]\n"
            )

            if verbose:
                # Verbose mode: show detailed plan for each session
                for session_info in sessions_to_sync:
                    _sync_single_session(
                        console=console,
                        config=config,
                        persona_name=persona_name,
                        session=session_info["session_id"],
                        session_dir=session_info["path"],
                        dry_run=True,
                        verbose=True,
                    )
            else:
                # Summary mode: show table with all sessions
                plans = []
                for session_info in sessions_to_sync:
                    plan = _analyze_session_plan(
                        config=config,
                        persona_name=persona_name,
                        session=session_info["session_id"],
                    )
                    plans.append(plan)

                _display_dry_run_summary(console, plans)
            return

        # Handle single session sync (simple output)
        if len(sessions_to_sync) == 1:
            session_info = sessions_to_sync[0]
            console.print(
                f"[cyan]Syncing history for session '{session_info['session_id']}'...[/cyan]\n"
            )

            result = _sync_single_session(
                console=console,
                config=config,
                persona_name=persona_name,
                session=session_info["session_id"],
                session_dir=session_info["path"],
                dry_run=False,
            )

            if result.error:
                console.print(
                    Panel(
                        Text.assemble(
                            ("✗ ", "red bold"),
                            ("Sync failed\n\n", "red"),
                            ("Error: ", "cyan"),
                            (result.error, "white"),
                        ),
                        title="Sync Results",
                        border_style="red",
                    )
                )
            else:
                console.print(
                    Panel(
                        Text.assemble(
                            ("✓ ", "green bold"),
                            ("Sync completed\n\n", "green"),
                            ("Succeeded: ", "cyan"),
                            (str(result.succeeded), "white"),
                            ("\n"),
                            ("Failed: ", "cyan"),
                            (str(result.failed), "white"),
                            ("\n"),
                            ("Conflicts: ", "cyan"),
                            (str(result.conflicts), "white"),
                            ("\n"),
                            ("Skipped: ", "cyan"),
                            (str(result.skipped), "white"),
                            ("\n"),
                            ("Duration: ", "cyan"),
                            (f"{result.duration:.2f}s", "white"),
                        ),
                        title="Sync Results",
                        border_style="green"
                        if not result.failed and not result.conflicts
                        else "yellow",
                    )
                )
            return

        # Handle multiple sessions with live progress display
        all_results = _sync_all_sessions_with_progress(
            console=console,
            config=config,
            persona_name=persona_name,
            sessions_to_sync=sessions_to_sync,
        )

        # Calculate totals
        total_succeeded = sum(r.succeeded for r in all_results)
        total_failed = sum(r.failed for r in all_results)
        total_conflicts = sum(r.conflicts for r in all_results)
        total_duration = sum(r.duration for r in all_results)
        sessions_succeeded = len([r for r in all_results if not r.error])
        errors = [(r.session_id, r.error) for r in all_results if r.error]

        # Display final summary
        console.print()
        console.print(
            Panel(
                Text.assemble(
                    ("✓ ", "green bold") if not errors else ("⚠ ", "yellow bold"),
                    (
                        "Sync completed\n\n"
                        if not errors
                        else "Sync completed with errors\n\n",
                        "green" if not errors else "yellow",
                    ),
                    ("Sessions synced: ", "cyan"),
                    (f"{sessions_succeeded}/{len(sessions_to_sync)}", "white"),
                    ("\n"),
                    ("Total operations: ", "cyan"),
                    (str(total_succeeded), "white"),
                    ("\n"),
                    ("Total failed: ", "cyan"),
                    (str(total_failed), "white"),
                    ("\n"),
                    ("Total conflicts: ", "cyan"),
                    (str(total_conflicts), "white"),
                    ("\n"),
                    ("Total duration: ", "cyan"),
                    (f"{total_duration:.2f}s", "white"),
                ),
                title="Sync Results (All Sessions)",
                border_style="green" if not errors else "yellow",
            )
        )

        # Show errors if any
        if errors:
            console.print("\n[red]Session errors:[/red]")
            for session_id, error in errors[:5]:
                console.print(f"  • {session_id}: {error}")
            if len(errors) > 5:
                console.print(f"  ... and {len(errors) - 5} more")

    except Exception as e:
        console.print(f"[red]Error during sync: {e}[/red]")
        raise
