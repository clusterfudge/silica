"""CLI commands for memory proxy synchronization.

This module provides commands for configuring and managing memory sync
with a remote memory proxy service.
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
from silica.developer.memory.sync_coordinator import sync_with_retry
from silica.developer.memory.llm_conflict_resolver import LLMConflictResolver
from silica.developer import personas


# Create the memory-sync command group
memory_sync_app = cyclopts.App(
    name="memory-sync", help="Manage memory proxy synchronization"
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


@memory_sync_app.command
def setup(
    url: Annotated[str, cyclopts.Parameter(help="Memory proxy service URL")],
    token: Annotated[str, cyclopts.Parameter(help="Authentication token")],
    *,
    enable: Annotated[bool, cyclopts.Parameter(help="Enable sync after setup")] = True,
):
    """Configure memory proxy connection.

    Sets up the remote memory proxy URL and authentication token.
    By default, also enables sync globally. Use --no-enable to configure
    without enabling.

    Example:
        silica memory-sync setup --url https://memory.example.com --token sec_xxx
    """
    console = _get_console()

    try:
        config = MemoryProxyConfig()
        config.setup(remote_url=url, auth_token=token, enable=enable)

        console.print(
            Panel(
                Text.assemble(
                    ("✓ ", "green bold"),
                    ("Memory proxy configured successfully\n\n", "green"),
                    ("URL: ", "cyan"),
                    (url, "white"),
                    ("\n"),
                    ("Enabled: ", "cyan"),
                    (str(enable), "white"),
                ),
                title="Setup Complete",
                border_style="green",
            )
        )

    except Exception as e:
        console.print(f"[red]Error during setup: {e}[/red]")
        raise


@memory_sync_app.command
def enable(
    *,
    persona: Annotated[
        Optional[str], cyclopts.Parameter(help="Persona to enable sync for")
    ] = None,
):
    """Enable memory sync.

    If --persona is specified, enables sync only for that persona.
    Otherwise, enables sync globally.

    Example:
        silica memory-sync enable
        silica memory-sync enable --persona autonomous_engineer
    """
    console = _get_console()

    try:
        config = MemoryProxyConfig()

        if not config.is_configured:
            console.print(
                "[red]Error: Memory proxy not configured. Run 'silica memory-sync setup' first.[/red]"
            )
            return

        if persona:
            config.set_persona_enabled(persona, True)
            console.print(
                f"[green]✓ Memory sync enabled for persona: {persona}[/green]"
            )
        else:
            config.set_global_enabled(True)
            console.print("[green]✓ Memory sync enabled globally[/green]")

    except Exception as e:
        console.print(f"[red]Error enabling sync: {e}[/red]")
        raise


@memory_sync_app.command
def disable(
    *,
    persona: Annotated[
        Optional[str], cyclopts.Parameter(help="Persona to disable sync for")
    ] = None,
):
    """Disable memory sync.

    If --persona is specified, disables sync only for that persona.
    Otherwise, disables sync globally.

    Example:
        silica memory-sync disable
        silica memory-sync disable --persona autonomous_engineer
    """
    console = _get_console()

    try:
        config = MemoryProxyConfig()

        if persona:
            config.set_persona_enabled(persona, False)
            console.print(
                f"[yellow]Memory sync disabled for persona: {persona}[/yellow]"
            )
        else:
            config.set_global_enabled(False)
            console.print("[yellow]Memory sync disabled globally[/yellow]")

    except Exception as e:
        console.print(f"[red]Error disabling sync: {e}[/red]")
        raise


@memory_sync_app.command
def status(
    *,
    persona: Annotated[
        Optional[str], cyclopts.Parameter(help="Persona to show status for")
    ] = None,
):
    """Show memory sync status and configuration.

    Displays current configuration, sync state, and any pending operations.

    Example:
        silica memory-sync status
        silica memory-sync status --persona autonomous_engineer
    """
    console = _get_console()

    try:
        config = MemoryProxyConfig()
        persona_dir, persona_name = _get_persona_directory(persona)

        # Create status table
        table = Table(title="Memory Sync Status", show_header=False, box=None)
        table.add_column("Key", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")

        # Configuration status
        table.add_row("Configured", "✓ Yes" if config.is_configured else "✗ No")

        if config.is_configured:
            table.add_row("Remote URL", config.remote_url)
            table.add_row(
                "Globally Enabled", "✓ Yes" if config.is_globally_enabled else "✗ No"
            )
            table.add_row("Persona", persona_name)
            table.add_row(
                "Persona Sync",
                "✓ Enabled"
                if config.is_persona_enabled(persona_name)
                else "✗ Disabled",
            )

            last_sync = config.get_last_sync(persona_name)
            if last_sync:
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                delta = now - last_sync

                # Format the time delta nicely
                if delta.total_seconds() < 60:
                    time_ago = f"{int(delta.total_seconds())} seconds ago"
                elif delta.total_seconds() < 3600:
                    time_ago = f"{int(delta.total_seconds() / 60)} minutes ago"
                elif delta.total_seconds() < 86400:
                    time_ago = f"{int(delta.total_seconds() / 3600)} hours ago"
                else:
                    time_ago = f"{int(delta.total_seconds() / 86400)} days ago"

                table.add_row(
                    "Last Sync",
                    f"{last_sync.strftime('%Y-%m-%d %H:%M:%S UTC')} ({time_ago})",
                )
            else:
                table.add_row("Last Sync", "Never")

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

        # Show sync status if enabled
        if config.is_sync_enabled(persona_name):
            console.print("\n[dim]To manually sync: silica memory-sync sync[/dim]")
            console.print("[dim]To test connection: silica memory-sync test[/dim]")

    except Exception as e:
        console.print(f"[red]Error getting status: {e}[/red]")
        raise


@memory_sync_app.command
def test():
    """Test connection to memory proxy service.

    Performs a health check to verify the service is reachable
    and authentication is working.

    Example:
        silica memory-sync test
    """
    console = _get_console()

    try:
        config = MemoryProxyConfig()

        if not config.is_configured:
            console.print(
                "[red]Error: Memory proxy not configured. Run 'silica memory-sync setup' first.[/red]"
            )
            return

        with console.status("[cyan]Testing connection...[/cyan]"):
            client = MemoryProxyClient(
                base_url=config.remote_url, token=config.auth_token
            )

            # Perform health check
            is_healthy = client.health_check()

        if is_healthy:
            console.print(
                Panel(
                    Text.assemble(
                        ("✓ ", "green bold"),
                        ("Connection successful\n\n", "green"),
                        ("URL: ", "cyan"),
                        (config.remote_url, "white"),
                    ),
                    title="Connection Test",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    Text.assemble(
                        ("✗ ", "red bold"),
                        ("Connection failed\n\n", "red"),
                        ("URL: ", "cyan"),
                        (config.remote_url, "white"),
                    ),
                    title="Connection Test",
                    border_style="red",
                )
            )

    except Exception as e:
        console.print(
            Panel(
                Text.assemble(
                    ("✗ ", "red bold"),
                    ("Connection failed\n\n", "red"),
                    ("Error: ", "cyan"),
                    (str(e), "white"),
                ),
                title="Connection Test",
                border_style="red",
            )
        )


@memory_sync_app.command
def migrate(
    *,
    persona: Annotated[
        Optional[str], cyclopts.Parameter(help="Persona to migrate (default: all)")
    ] = None,
    dry_run: Annotated[
        bool, cyclopts.Parameter(help="Show what would be migrated without doing it")
    ] = False,
):
    """Migrate persona.md to memory/ subdirectory.

    This command moves persona.md from the legacy location
    (~/.silica/personas/{name}/persona.md) to the new location
    (~/.silica/personas/{name}/memory/persona.md).

    If no persona is specified, attempts to migrate all personas.

    Example:
        silica memory-sync migrate --dry-run
        silica memory-sync migrate
        silica memory-sync migrate --persona autonomous_engineer
    """
    console = _get_console()

    try:
        personas_dir = Path.home() / ".silica" / "personas"

        if not personas_dir.exists():
            console.print("[yellow]No personas directory found[/yellow]")
            return

        # Determine which personas to migrate
        if persona:
            personas_to_check = [persona]
        else:
            # Get all persona directories
            personas_to_check = [
                d.name for d in personas_dir.iterdir() if d.is_dir()
            ]

        if not personas_to_check:
            console.print("[yellow]No personas found[/yellow]")
            return

        console.print(f"[cyan]Checking {len(personas_to_check)} persona(s)...[/cyan]\n")

        migrated = []
        skipped = []
        errors = []

        for persona_name in personas_to_check:
            persona_dir = personas_dir / persona_name
            legacy_file = persona_dir / "persona.md"
            memory_dir = persona_dir / "memory"
            new_file = memory_dir / "persona.md"

            # Check if migration is needed
            if not legacy_file.exists():
                skipped.append((persona_name, "No legacy persona.md file"))
                continue

            if new_file.exists():
                skipped.append((persona_name, "New location already exists"))
                continue

            # Perform migration
            if dry_run:
                migrated.append((persona_name, str(legacy_file), str(new_file)))
            else:
                try:
                    # Use the migration helper from personas module
                    success = personas.migrate_persona_md_to_memory(persona_name)
                    if success:
                        migrated.append((persona_name, str(legacy_file), str(new_file)))
                    else:
                        errors.append((persona_name, "Migration failed (unknown reason)"))
                except Exception as e:
                    errors.append((persona_name, str(e)))

        # Display results
        if migrated:
            if dry_run:
                console.print(
                    Panel(
                        f"[yellow]Would migrate {len(migrated)} persona(s)[/yellow]",
                        title="Dry Run Results",
                        border_style="yellow",
                    )
                )
            else:
                console.print(
                    Panel(
                        f"[green]Successfully migrated {len(migrated)} persona(s)[/green]",
                        title="Migration Complete",
                        border_style="green",
                    )
                )

            console.print("\n[cyan]Migrated:[/cyan]")
            for persona_name, legacy, new in migrated:
                console.print(f"  ✓ {persona_name}")
                console.print(f"    {legacy} → {new}")

        if skipped:
            console.print(f"\n[dim]Skipped {len(skipped)} persona(s):[/dim]")
            for persona_name, reason in skipped:
                console.print(f"  • {persona_name}: {reason}")

        if errors:
            console.print(f"\n[red]Errors in {len(errors)} persona(s):[/red]")
            for persona_name, error in errors:
                console.print(f"  ✗ {persona_name}: {error}")

        if not migrated and not errors:
            console.print("[green]No migration needed - all personas up to date[/green]")

    except Exception as e:
        console.print(f"[red]Error during migration: {e}[/red]")
        raise


@memory_sync_app.command
def sync(
    *,
    persona: Annotated[
        Optional[str], cyclopts.Parameter(help="Persona to sync")
    ] = None,
    dry_run: Annotated[
        bool, cyclopts.Parameter(help="Show plan without executing")
    ] = False,
):
    """Manually trigger memory synchronization.

    Performs bi-directional sync between local memory and remote storage.
    Uses automatic conflict resolution via LLM when needed.

    Example:
        silica memory-sync sync
        silica memory-sync sync --dry-run
        silica memory-sync sync --persona autonomous_engineer
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

        if not config.is_sync_enabled(persona_name):
            console.print(
                f"[yellow]Warning: Sync is disabled for persona '{persona_name}'[/yellow]"
            )
            console.print("[dim]Run 'silica memory-sync enable' to enable sync[/dim]")
            return

        # Get Anthropic API key for LLM conflict resolution
        import os

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if not anthropic_key:
            console.print(
                "[yellow]Warning: ANTHROPIC_API_KEY not set. Conflict resolution will fail if conflicts occur.[/yellow]"
            )

        # Set up sync engine
        from silica.developer.memory.sync_config import SyncConfig

        # Create conflict resolver if we have an API key
        conflict_resolver = None
        if anthropic_key:
            from anthropic import Anthropic

            client = Anthropic(api_key=anthropic_key)
            conflict_resolver = LLMConflictResolver(client=client)

        # Create proxy client
        client = MemoryProxyClient(base_url=config.remote_url, token=config.auth_token)

        # Create sync configuration for memory
        sync_config = SyncConfig.for_memory(persona_name)

        # Create sync engine
        sync_engine = SyncEngine(
            client=client,
            config=sync_config,
            conflict_resolver=conflict_resolver,
        )

        if dry_run:
            console.print(
                f"[cyan]Analyzing sync plan for persona '{persona_name}'...[/cyan]\n"
            )

            # This is a placeholder - the actual sync_with_retry doesn't have a dry-run mode yet
            # We would need to add a method to just analyze without executing
            console.print(
                "[yellow]Dry-run mode: Would perform sync analysis here[/yellow]"
            )
            console.print("[dim]Full dry-run implementation coming soon[/dim]")
            return

        console.print(f"[cyan]Syncing memory for persona '{persona_name}'...[/cyan]\n")

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

        # Update last sync timestamp
        config.set_last_sync(persona_name)

    except Exception as e:
        console.print(f"[red]Error during sync: {e}[/red]")
        raise
