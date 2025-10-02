"""
CLI commands for Memory V2 operations.
"""

import asyncio
import contextlib
from pathlib import Path
from typing import Optional, Any

from cyclopts import App
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)

from silica.developer.memory_v2.migration import (
    scan_v1_memory,
    load_migration_state,
    save_migration_state,
    extract_information_from_file,
    MigrationState,
)
from silica.developer.memory_v2.manager import MemoryManager
from silica.developer.memory_v2.operations import agentic_write
from silica.developer.context import AgentContext
from silica.developer.user_interface import UserInterface
from silica.developer.sandbox import SandboxMode

app = App(name="memory-v2", help="Memory V2 management commands")
console = Console()


class QuietMigrationUI(UserInterface):
    """A minimal UI that doesn't create live displays (prevents conflicts with progress bars)."""

    def __init__(self, console: Console):
        self.console = console
        self._sandbox_mode = SandboxMode.ALLOW_ALL

    async def get_user_input(self, prompt: str = "") -> str:
        # Migration is non-interactive
        return ""

    def display_welcome_message(self) -> None:
        pass

    @contextlib.contextmanager
    def status(self, message: str, spinner: str = None, update=False):
        """No-op status - prevents live display conflicts."""
        # Just yield without creating a status display
        yield None

    def handle_system_message(self, message, markdown=True, live=None):
        # Silently ignore during migration
        pass

    def handle_user_input(self, message):
        pass

    def handle_assistant_message(self, message):
        pass

    def handle_tool_use(self, tool_name, tool_input):
        pass

    def handle_tool_result(self, tool_name, result, live=None):
        pass

    def display_token_count(
        self,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        total_cost,
        cached_tokens=None,
        conversation_size=None,
        context_window=None,
    ):
        pass

    def permission_callback(self, operation, path, sandbox_mode, action_arguments):
        return True

    def permission_rendering_callback(self, operation, path, action_arguments):
        return True

    def bare(self, message: str | Any, live=None) -> None:
        # Silently ignore during migration
        pass


@app.command
def migrate(
    v1_path: Optional[str] = None,
    persona: str = "default",
    resume: bool = True,
    max_files: int = 0,
):
    """Migrate V1 memory to V2 using intelligent AI extraction.

    This command scans your V1 memory files chronologically and uses AI to
    extract salient information, storing it in the new V2 system with organic
    organization.

    Args:
        v1_path: Path to V1 memory directory (default: ~/.silica/memory)
        persona: Target persona for V2 memory (default: default)
        resume: Resume from last checkpoint (default: True)
        max_files: Maximum files to process (0 = all, useful for testing)

    Examples:
        # Test migration with first 10 files
        silica memory-v2 migrate --max-files 10

        # Full migration to default persona
        silica memory-v2 migrate

        # Migrate to specific persona
        silica memory-v2 migrate --persona coding_agent

        # Start fresh (ignore previous progress)
        silica memory-v2 migrate --no-resume

        # Custom V1 path
        silica memory-v2 migrate --v1-path /path/to/old/memory
    """
    asyncio.run(_migrate_async(v1_path, persona, resume, max_files))


async def _migrate_async(
    v1_path: Optional[str],
    persona: str,
    resume: bool,
    max_files: int,
):
    """Async implementation of migration."""
    from datetime import datetime

    # Parse V1 path
    v1_path_obj = Path(v1_path) if v1_path else Path.home() / ".silica" / "memory"

    if not v1_path_obj.exists():
        console.print(
            f"[red]❌ V1 memory directory not found:[/red] {v1_path_obj}",
            style="bold",
        )
        console.print("\nMake sure the V1 memory directory exists.")
        return

    # Initialize V2 storage for target persona
    console.print(f"[blue]📂 Initializing V2 memory for persona:[/blue] {persona}")
    memory_manager = MemoryManager(persona_name=persona)
    storage = memory_manager.storage

    # Scan V1 memory
    console.print(f"[blue]🔍 Scanning V1 memory:[/blue] {v1_path_obj}")
    v1_files = scan_v1_memory(v1_path_obj)

    if not v1_files:
        console.print("[red]❌ No V1 memory files found[/red]")
        return

    console.print(f"[green]✓ Found {len(v1_files)} files[/green]\n")

    # Load existing state if resuming
    state = None
    if resume:
        state = load_migration_state(storage)

    # Display status
    if state and resume:
        processed_count = len(state.processed_files)
        remaining = state.total_files - processed_count

        if remaining == 0:
            console.print("[green]✅ Migration already complete![/green]\n")
            console.print(f"Processed: {state.total_files} files")
            console.print(f"Started: {state.started_at}")
            console.print(f"Completed: {state.last_updated}")
            console.print("\nUse --no-resume to start fresh.")
            return

        console.print("[yellow]📂 Resuming migration...[/yellow]")
        console.print(f"Already processed: {processed_count}/{state.total_files} files")
        console.print(f"Remaining: {remaining} files\n")
    else:
        console.print("[blue]📂 Starting new migration...[/blue]")
        console.print(f"Total files: {len(v1_files)}\n")

    # Initialize state if needed
    if state is None:
        state = MigrationState(
            started_at=datetime.now().isoformat(),
            last_updated=datetime.now().isoformat(),
            processed_files=[],
            total_files=len(v1_files),
        )

    # Filter to unprocessed files
    processed_paths = {pf["path"] for pf in state.processed_files}
    files_to_process = [f for f in v1_files if f.path not in processed_paths]

    # Apply max_files limit
    if max_files and max_files > 0:
        files_to_process = files_to_process[:max_files]
        console.print(
            f"[yellow]⚠️  Processing max {max_files} files (test mode)[/yellow]\n"
        )

    if not files_to_process:
        console.print("[green]✅ No files to process[/green]")
        return

    # Create minimal agent context for AI operations
    from silica.developer.models import get_model
    from silica.developer.sandbox import Sandbox, SandboxMode
    from uuid import uuid4
    import os

    # Create a quiet UI that doesn't use live displays
    ui = QuietMigrationUI(console=console)
    model_spec = get_model("sonnet")  # Use sonnet for migration

    # Create sandbox
    sandbox = Sandbox(
        os.getcwd(),
        mode=SandboxMode.ALLOW_ALL,
        permission_check_callback=ui.permission_callback,
        permission_check_rendering_callback=ui.permission_rendering_callback,
    )

    # Create context with our memory_manager (not a new one)
    context = AgentContext(
        parent_session_id=None,
        session_id=str(uuid4()),
        model_spec=model_spec,
        sandbox=sandbox,
        user_interface=ui,
        usage=[],
        memory_manager=memory_manager,  # Use the one we created earlier!
        cli_args=["--persona", persona],
    )

    # Process files with progress bar
    success_count = 0
    error_count = 0
    errors = []

    console.print(
        f"[blue]Starting to process {len(files_to_process)} files...[/blue]\n"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            "Migrating V1 memory...",
            total=len(files_to_process),
        )

        for i, v1_file in enumerate(files_to_process):
            # Update progress description
            progress.update(
                task,
                description=f"Processing: {v1_file.path}",
                completed=i,
            )

            try:
                console.print(f"[dim]Extracting from: {v1_file.path}[/dim]")

                # Extract information using AI
                extracted_info = await extract_information_from_file(v1_file, context)

                console.print(f"[dim]Extracted {len(extracted_info)} chars[/dim]")

                # Store using agentic write to root
                console.print("[dim]Writing to V2 storage...[/dim]")
                result = await agentic_write(
                    storage=storage,
                    path="",  # Root, let organic growth handle organization
                    new_content=f"# Migrated from V1: {v1_file.path}\n\n{extracted_info}",
                    context=context,
                    instruction=f"This is information migrated from the old memory system (file: {v1_file.path}). "
                    f"Incorporate appropriately, organizing by topic. Avoid duplication.",
                )

                if result.success:
                    success_count += 1
                    console.print(
                        f"[green]✓ Successfully migrated: {v1_file.path}[/green]"
                    )
                    state.processed_files.append(
                        {
                            "path": v1_file.path,
                            "processed_at": datetime.now().isoformat(),
                            "success": True,
                            "size_bytes": v1_file.size_bytes,
                        }
                    )
                else:
                    error_count += 1
                    errors.append(f"{v1_file.path}: Write failed")
                    console.print(f"[red]✗ Write failed: {v1_file.path}[/red]")
                    state.processed_files.append(
                        {
                            "path": v1_file.path,
                            "processed_at": datetime.now().isoformat(),
                            "success": False,
                            "error": "Write failed",
                        }
                    )

            except Exception as e:
                error_count += 1
                error_msg = str(e)
                errors.append(f"{v1_file.path}: {error_msg}")
                console.print(f"[red]✗ Error: {v1_file.path} - {error_msg}[/red]")
                import traceback

                console.print(f"[dim]{traceback.format_exc()}[/dim]")
                state.processed_files.append(
                    {
                        "path": v1_file.path,
                        "processed_at": datetime.now().isoformat(),
                        "success": False,
                        "error": error_msg,
                    }
                )

            # Save state after each file
            save_migration_state(storage, state)

            # Update progress
            progress.update(task, completed=i + 1)

        # Final update
        progress.update(task, completed=len(files_to_process))

    # Check if migration is complete
    if len(state.processed_files) >= state.total_files:
        state.completed = True
        save_migration_state(storage, state)

    # Display results
    console.print("\n" + "=" * 60)
    console.print("[green]✅ Migration batch complete![/green]\n")
    console.print(f"Files processed: {success_count}")
    if error_count > 0:
        console.print(f"[yellow]Errors: {error_count}[/yellow]")

    console.print(
        f"\n[bold]Total progress: {len(state.processed_files)}/{state.total_files} files[/bold]"
    )

    if state.completed:
        console.print("\n[green bold]🎉 Migration fully complete![/green bold]")
    else:
        remaining = state.total_files - len(state.processed_files)
        console.print(f"\n[blue]Remaining: {remaining} files[/blue]")
        console.print("Run the command again to continue migration.")

    if errors:
        console.print("\n[yellow]⚠️  Errors encountered:[/yellow]")
        for error in errors[:5]:  # Show first 5
            console.print(f"  • {error}")
        if len(errors) > 5:
            console.print(f"  ... and {len(errors) - 5} more")

    console.print()
