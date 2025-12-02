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


@history_sync_app.command
def sync(
    *,
    session: Annotated[str, cyclopts.Parameter(help="Session ID to sync")],
    persona: Annotated[Optional[str], cyclopts.Parameter(help="Persona name")] = None,
    dry_run: Annotated[
        bool, cyclopts.Parameter(help="Show plan without executing")
    ] = False,
):
    """Sync conversation history for a specific session.

    Performs bi-directional sync between local session history and remote storage.
    Uses automatic conflict resolution via LLM when needed.

    Example:
        silica history-sync sync --session session-123
        silica history-sync sync --session session-123 --dry-run
        silica history-sync sync --session session-123 --persona autonomous_engineer
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

        # Check if session exists
        session_dir = persona_dir / "history" / session
        if not session_dir.exists():
            console.print(f"[red]Error: Session '{session}' not found[/red]")
            return

        # Get Anthropic API key for LLM conflict resolution
        import os

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if not anthropic_key:
            console.print(
                "[yellow]Warning: ANTHROPIC_API_KEY not set. Conflict resolution will fail if conflicts occur.[/yellow]"
            )

        # Create conflict resolver if we have an API key
        conflict_resolver = None
        if anthropic_key:
            from anthropic import Anthropic

            client = Anthropic(api_key=anthropic_key)
            conflict_resolver = LLMConflictResolver(client=client)

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
            console.print(
                f"[cyan]Analyzing sync plan for session '{session}'...[/cyan]\n"
            )

            # Analyze what would be synced
            plan = sync_engine.analyze_sync_operations()

            console.print("[bold]Sync Plan:[/bold]")
            console.print(f"  Uploads:        {len(plan.upload)}")
            console.print(f"  Downloads:      {len(plan.download)}")
            console.print(f"  Conflicts:      {len(plan.conflicts)}")
            console.print(f"  Total ops:      {plan.total_operations}")

            if plan.upload:
                console.print("\n[bold cyan]Files to upload:[/bold cyan]")
                for op in plan.upload[:10]:  # Show first 10
                    console.print(f"  • {op.path}")
                if len(plan.upload) > 10:
                    console.print(f"  ... and {len(plan.upload) - 10} more")

            if plan.download:
                console.print("\n[bold cyan]Files to download:[/bold cyan]")
                for op in plan.download[:10]:  # Show first 10
                    console.print(f"  • {op.path}")
                if len(plan.download) > 10:
                    console.print(f"  ... and {len(plan.download) - 10} more")

            if plan.conflicts:
                console.print("\n[bold yellow]Conflicts:[/bold yellow]")
                for op in plan.conflicts:
                    console.print(f"  • {op.path}")

            return

        console.print(f"[cyan]Syncing history for session '{session}'...[/cyan]\n")

        # Perform sync with retry and automatic conflict resolution
        result = sync_with_retry(
            sync_engine=sync_engine, max_retries=3, show_progress=True
        )

        # Display results
        console.print(
            Panel(
                Text.assemble(
                    ("✓ ", "green bold"),
                    ("Sync completed\n\n", "green"),
                    ("Succeeded: ", "cyan"),
                    (str(len(result.succeeded)), "white"),
                    ("\n"),
                    ("Failed: ", "cyan"),
                    (str(len(result.failed)), "white"),
                    ("\n"),
                    ("Conflicts: ", "cyan"),
                    (str(len(result.conflicts)), "white"),
                    ("\n"),
                    ("Skipped: ", "cyan"),
                    (str(len(result.skipped)), "white"),
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

        # Show details about failures
        if result.failed:
            console.print("\n[red]Failed operations:[/red]")
            for op in result.failed[:5]:  # Show first 5
                console.print(f"  • {op.type}: {op.path}")
            if len(result.failed) > 5:
                console.print(f"  ... and {len(result.failed) - 5} more")

        # Show details about conflicts
        if result.conflicts:
            console.print("\n[yellow]Conflicts:[/yellow]")
            for op in result.conflicts[:5]:  # Show first 5
                console.print(f"  • {op.path}")
            if len(result.conflicts) > 5:
                console.print(f"  ... and {len(result.conflicts) - 5} more")

    except Exception as e:
        console.print(f"[red]Error during sync: {e}[/red]")
        raise
