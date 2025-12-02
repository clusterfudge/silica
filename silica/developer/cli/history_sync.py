"""CLI commands for history sync.

This module provides commands for syncing conversation history per session.
"""

from pathlib import Path
from typing import Annotated, Optional

import cyclopts
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from silica.developer.memory.proxy_config import MemoryProxyConfig
from silica.developer.memory.proxy_client import MemoryProxyClient
from silica.developer.memory.sync import SyncEngine
from silica.developer.memory.sync_config import SyncConfig
from silica.developer.memory.sync_coordinator import sync_with_retry
from silica.developer.memory.llm_conflict_resolver import LLMConflictResolver
from silica.developer import personas


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


def _sync_single_session(
    console: Console,
    config: MemoryProxyConfig,
    persona_name: str,
    session: str,
    session_dir: Path,
    dry_run: bool = False,
) -> dict:
    """Sync a single session.

    Args:
        console: Rich console for output
        config: Memory proxy configuration
        persona_name: Name of the persona
        session: Session ID
        session_dir: Path to the session directory
        dry_run: If True, only analyze without executing

    Returns:
        Dict with keys: session_id, succeeded, failed, conflicts, skipped, duration, error
    """
    import os

    from silica.developer.cli.sync_helpers import display_sync_plan

    result_info = {
        "session_id": session,
        "succeeded": 0,
        "failed": 0,
        "conflicts": 0,
        "skipped": 0,
        "duration": 0.0,
        "error": None,
    }

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
            display_sync_plan(console, plan, context=f"session '{session}'")
            result_info["succeeded"] = plan.total_operations
            result_info["conflicts"] = len(plan.conflicts)
            return result_info

        # Perform sync with retry and automatic conflict resolution
        result = sync_with_retry(
            sync_engine=sync_engine, max_retries=3, show_progress=False
        )

        result_info["succeeded"] = len(result.succeeded)
        result_info["failed"] = len(result.failed)
        result_info["conflicts"] = len(result.conflicts)
        result_info["skipped"] = len(result.skipped)
        result_info["duration"] = result.duration

        return result_info

    except Exception as e:
        result_info["error"] = str(e)
        return result_info


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
):
    """Sync conversation history for sessions.

    If --session is specified, syncs only that session.
    If --session is omitted, syncs ALL sessions for the persona.

    Performs bi-directional sync between local session history and remote storage.
    Uses automatic conflict resolution via LLM when needed.

    Example:
        silica history-sync sync                              # Sync all sessions
        silica history-sync sync --session session-123        # Sync specific session
        silica history-sync sync --dry-run                    # Preview all sessions
        silica history-sync sync --session session-123 --dry-run
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

        # Get Anthropic API key warning
        import os

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

        # Show what we're about to do
        if len(sessions_to_sync) == 1:
            if dry_run:
                console.print(
                    f"[cyan]Analyzing sync plan for session '{sessions_to_sync[0]['session_id']}'...[/cyan]"
                )
            else:
                console.print(
                    f"[cyan]Syncing history for session '{sessions_to_sync[0]['session_id']}'...[/cyan]\n"
                )
        else:
            if dry_run:
                console.print(
                    f"[cyan]Analyzing sync plan for {len(sessions_to_sync)} sessions...[/cyan]\n"
                )
            else:
                console.print(
                    f"[cyan]Syncing history for {len(sessions_to_sync)} sessions...[/cyan]\n"
                )

        # Sync each session
        all_results = []
        total_succeeded = 0
        total_failed = 0
        total_conflicts = 0
        total_skipped = 0
        total_duration = 0.0
        errors = []

        for session_info in sessions_to_sync:
            session_id = session_info["session_id"]
            session_path = session_info["path"]

            if len(sessions_to_sync) > 1 and not dry_run:
                console.print(f"[dim]Syncing {session_id}...[/dim]")

            result = _sync_single_session(
                console=console,
                config=config,
                persona_name=persona_name,
                session=session_id,
                session_dir=session_path,
                dry_run=dry_run,
            )

            all_results.append(result)
            total_succeeded += result["succeeded"]
            total_failed += result["failed"]
            total_conflicts += result["conflicts"]
            total_skipped += result["skipped"]
            total_duration += result["duration"]

            if result["error"]:
                errors.append((session_id, result["error"]))

        # For dry-run, the display is already done per-session
        if dry_run:
            return

        # Display aggregated results
        if len(sessions_to_sync) == 1:
            # Single session - show detailed results
            result = all_results[0]
            if result["error"]:
                console.print(
                    Panel(
                        Text.assemble(
                            ("✗ ", "red bold"),
                            ("Sync failed\n\n", "red"),
                            ("Error: ", "cyan"),
                            (result["error"], "white"),
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
                            (str(result["succeeded"]), "white"),
                            ("\n"),
                            ("Failed: ", "cyan"),
                            (str(result["failed"]), "white"),
                            ("\n"),
                            ("Conflicts: ", "cyan"),
                            (str(result["conflicts"]), "white"),
                            ("\n"),
                            ("Skipped: ", "cyan"),
                            (str(result["skipped"]), "white"),
                            ("\n"),
                            ("Duration: ", "cyan"),
                            (f"{result['duration']:.2f}s", "white"),
                        ),
                        title="Sync Results",
                        border_style="green"
                        if not result["failed"] and not result["conflicts"]
                        else "yellow",
                    )
                )
        else:
            # Multiple sessions - show summary
            sessions_succeeded = len([r for r in all_results if not r["error"]])

            console.print(
                Panel(
                    Text.assemble(
                        ("✓ ", "green bold") if not errors else ("⚠ ", "yellow bold"),
                        (
                            "Sync completed\n\n"
                            if not errors
                            else "Sync completed with errors\n\n"
                        ),
                        ("green" if not errors else "yellow",),
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
