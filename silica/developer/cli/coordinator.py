"""Coordinator CLI command.

Provides the `silica coordinator` command for starting and managing
coordination sessions where a coordinator agent orchestrates multiple workers.
"""

import asyncio
from pathlib import Path
from typing import Optional, Annotated

import cyclopts
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from silica.developer.coordination.session import (
    CoordinationSession,
    list_sessions,
    delete_session,
)
from silica.developer.tools.coordination import set_current_session

console = Console()

# Create the coordinator app
coordinator_app = cyclopts.App(
    name="coordinator",
    help="Multi-agent coordination mode",
)


@coordinator_app.command(name="new")
def coordinator_new(
    name: Annotated[
        str,
        cyclopts.Parameter(help="Display name for the coordination session"),
    ] = "Coordination Session",
    deaddrop_url: Annotated[
        Optional[str],
        cyclopts.Parameter(help="Override deaddrop server URL"),
    ] = None,
):
    """Create a new coordination session.

    Creates a new deaddrop namespace and starts the coordinator agent.
    """
    from deadrop import Deaddrop

    console.print("\n[bold cyan]🤝 Creating Coordination Session[/bold cyan]\n")

    # Create deaddrop client
    if deaddrop_url:
        deaddrop = Deaddrop(deaddrop_url)
        console.print(f"[dim]Using custom deaddrop server: {deaddrop_url}[/dim]")
    else:
        deaddrop = Deaddrop()
        console.print("[dim]Using default deaddrop server[/dim]")

    # Create the session
    try:
        session = CoordinationSession.create_session(deaddrop, name)
    except Exception as e:
        console.print(f"[red]Failed to create session: {e}[/red]")
        return

    console.print(f"[green]✓ Session created: {session.session_id}[/green]")
    console.print(f"[dim]Namespace: {session.namespace_id}[/dim]")
    console.print(
        f"[dim]Session saved to: ~/.silica/coordination/{session.session_id}.json[/dim]"
    )
    console.print()

    # Start the coordinator agent loop
    _run_coordinator_agent(session)


@coordinator_app.command(name="resume")
def coordinator_resume(
    session_id: Annotated[
        str,
        cyclopts.Parameter(help="Session ID to resume"),
    ],
    deaddrop_url: Annotated[
        Optional[str],
        cyclopts.Parameter(help="Override deaddrop server URL"),
    ] = None,
):
    """Resume an existing coordination session.

    Reconnects to a previously created session and restarts the coordinator agent.
    """
    from deadrop import Deaddrop

    console.print(
        f"\n[bold cyan]🤝 Resuming Coordination Session: {session_id}[/bold cyan]\n"
    )

    # Create deaddrop client
    if deaddrop_url:
        deaddrop = Deaddrop(deaddrop_url)
    else:
        deaddrop = Deaddrop()

    # Resume the session
    try:
        session = CoordinationSession.resume_session(deaddrop, session_id=session_id)
    except FileNotFoundError:
        console.print(f"[red]Session not found: {session_id}[/red]")
        console.print(
            "[dim]Use 'silica coordinator list' to see available sessions[/dim]"
        )
        return
    except Exception as e:
        console.print(f"[red]Failed to resume session: {e}[/red]")
        return

    state = session.get_state()
    console.print(f"[green]✓ Session resumed: {state['display_name']}[/green]")
    console.print(f"[dim]Agents: {len(state.get('agents', {}))}[/dim]")
    console.print(f"[dim]Humans: {len(state.get('humans', {}))}[/dim]")
    console.print()

    # Start the coordinator agent loop
    _run_coordinator_agent(session)


@coordinator_app.command(name="list")
def coordinator_list():
    """List all saved coordination sessions."""
    sessions = list_sessions()

    if not sessions:
        console.print("[yellow]No coordination sessions found.[/yellow]")
        console.print("[dim]Use 'silica coordinator new' to create one.[/dim]")
        return

    table = Table(title="Coordination Sessions")
    table.add_column("Session ID", style="cyan")
    table.add_column("Name")
    table.add_column("Agents", justify="right")
    table.add_column("Created")

    for s in sessions:
        table.add_row(
            s["session_id"],
            s.get("display_name", ""),
            str(s.get("agent_count", 0)),
            s.get("created_at", "")[:10] if s.get("created_at") else "",
        )

    console.print(table)


@coordinator_app.command(name="delete")
def coordinator_delete(
    session_id: Annotated[
        str,
        cyclopts.Parameter(help="Session ID to delete"),
    ],
    force: Annotated[
        bool,
        cyclopts.Parameter("--force", "-f", help="Skip confirmation"),
    ] = False,
):
    """Delete a saved coordination session."""
    if not force:
        confirm = console.input(f"Delete session [cyan]{session_id}[/cyan]? [y/N] ")
        if confirm.lower() != "y":
            console.print("[yellow]Cancelled[/yellow]")
            return

    if delete_session(session_id):
        console.print(f"[green]✓ Session deleted: {session_id}[/green]")
    else:
        console.print(f"[red]Session not found: {session_id}[/red]")


@coordinator_app.command(name="info")
def coordinator_info(
    session_id: Annotated[
        str,
        cyclopts.Parameter(help="Session ID to inspect"),
    ],
):
    """Show detailed information about a coordination session."""
    from deadrop import Deaddrop

    deaddrop = Deaddrop()

    try:
        session = CoordinationSession.resume_session(deaddrop, session_id=session_id)
    except FileNotFoundError:
        console.print(f"[red]Session not found: {session_id}[/red]")
        return
    except Exception as e:
        console.print(f"[red]Failed to load session: {e}[/red]")
        return

    state = session.get_state()

    console.print(
        Panel(
            f"[bold]{state['display_name']}[/bold]\n"
            f"Session ID: {state['session_id']}\n"
            f"Created: {state['created_at']}\n"
            f"Namespace: {state['namespace_id']}",
            title="Session Info",
        )
    )

    # Agents
    agents = state.get("agents", {})
    if agents:
        table = Table(title="Agents")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("State")
        table.add_column("Workspace")

        for agent_id, agent in agents.items():
            state_str = agent.get("state", "unknown")
            state_style = {
                "idle": "green",
                "working": "yellow",
                "terminated": "red",
            }.get(state_str, "white")

            table.add_row(
                agent_id,
                agent.get("display_name", ""),
                f"[{state_style}]{state_str}[/{state_style}]",
                agent.get("workspace_name", ""),
            )

        console.print(table)
    else:
        console.print("[dim]No agents registered[/dim]")

    # Humans
    humans = state.get("humans", {})
    if humans:
        console.print(f"\n[bold]Human Participants:[/bold] {len(humans)}")
        for identity_id, human in humans.items():
            console.print(f"  • {human.get('display_name', identity_id)}")

    # Pending permissions
    pending = state.get("pending_permissions", {})
    if pending:
        pending_count = sum(1 for p in pending.values() if p.get("status") == "pending")
        if pending_count:
            console.print(f"\n[yellow]⚠ Pending permissions: {pending_count}[/yellow]")


def _run_coordinator_agent(session: CoordinationSession):
    """Run the coordinator agent loop.

    Sets up the coordinator persona and runs the agent loop with
    coordination tools available.
    """
    from silica.developer.agent_loop import run
    from silica.developer.context import AgentContext
    from silica.developer.models import get_model
    from silica.developer.sandbox import SandboxMode, Sandbox
    from silica.developer.hybrid_interface import HybridUserInterface
    from silica.developer.personas.coordinator_agent import (
        PERSONA as COORDINATOR_PERSONA,
        TOOL_GROUPS,
        MODEL,
    )
    from silica.developer.utils import wrap_text_as_content_block
    from uuid import uuid4

    # Set as current session for tools
    set_current_session(session)

    # Create user interface
    user_interface = HybridUserInterface()

    # Get model spec (coordinator uses specified model, typically sonnet)
    model_spec = get_model(MODEL)

    # Create sandbox (coordinator has limited permissions)
    sandbox = Sandbox(
        root_directory=str(Path.cwd()),
        mode=SandboxMode.ALLOW_ALL,  # Coordinator doesn't do file ops
        permission_check_callback=user_interface.permission_callback,
        permission_check_rendering_callback=user_interface.permission_rendering_callback,
    )

    # Create persona directory for history
    persona_dir = Path.home() / ".silica" / "personas" / "coordinator"
    persona_dir.mkdir(parents=True, exist_ok=True)

    # Memory manager
    from silica.developer.memory import MemoryManager

    memory_manager = MemoryManager(base_dir=persona_dir / "memory")

    # Create context
    context = AgentContext(
        session_id=str(uuid4()),
        parent_session_id=None,
        model_spec=model_spec,
        sandbox=sandbox,
        user_interface=user_interface,
        usage=[],
        memory_manager=memory_manager,
        cli_args=None,
        history_base_dir=persona_dir,
    )

    # Build initial prompt
    state = session.get_state()
    initial_prompt = f"""You are now running as a **Coordinator Agent** for session "{state['display_name']}" (ID: {session.session_id}).

**Your coordination tools are ready:**
- `spawn_agent` - Create new worker agents
- `message_agent` - Send tasks to workers
- `poll_messages` - Receive updates from workers
- `list_agents` - View agent status
- `grant_permission` - Handle permission requests
- And more...

**Session State:**
- Agents: {len(state.get('agents', {}))}
- Humans: {len(state.get('humans', {}))}

What would you like to coordinate? You can:
1. Spawn workers to execute tasks
2. Check on existing workers
3. Handle pending messages or permissions

I'm ready to help orchestrate your multi-agent workflow."""

    # Display welcome
    console.print(
        Panel(
            f"[bold green]Coordinator Agent Active[/bold green]\n\n"
            f"Session: {session.session_id}\n"
            f"Model: {MODEL}\n"
            f"Tools: {', '.join(TOOL_GROUPS)}",
            title="🤝 Coordination Mode",
        )
    )

    # Run the agent loop
    try:
        asyncio.run(
            run(
                agent_context=context,
                initial_prompt=initial_prompt,
                system_prompt=wrap_text_as_content_block(COORDINATOR_PERSONA),
                tool_names=TOOL_GROUPS,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Coordinator session ended.[/yellow]")
    finally:
        set_current_session(None)


# Default command (same as 'new')
@coordinator_app.default
def coordinator_default():
    """Start coordinator mode (same as 'silica coordinator new')."""
    coordinator_new()
