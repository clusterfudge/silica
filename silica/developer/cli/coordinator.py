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
from rich.prompt import Prompt, Confirm

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


def _ensure_deaddrop_configured():
    """Ensure deaddrop is configured, running init wizard if needed.

    Returns:
        Configured Deaddrop client
    """
    from deadrop import Deaddrop
    from deadrop.config import GlobalConfig, init_wizard

    if not GlobalConfig.exists():
        console.print("[yellow]Deaddrop not configured.[/yellow]")
        console.print("Let's set it up first.\n")
        init_wizard()
        console.print()

    config = GlobalConfig.load()
    return Deaddrop.remote(url=config.url, bearer_token=config.bearer_token)


@coordinator_app.command(name="new")
def coordinator_new(
    name: Annotated[
        Optional[str],
        cyclopts.Parameter(help="Display name for the coordination session"),
    ] = None,
):
    """Create a new coordination session.

    Creates a new deaddrop namespace and starts the coordinator agent.
    """
    console.print("\n[bold cyan]🤝 Creating Coordination Session[/bold cyan]\n")

    # Ensure deaddrop is configured
    deaddrop = _ensure_deaddrop_configured()
    console.print(f"[dim]Using deaddrop: {deaddrop.location}[/dim]\n")

    # Prompt for name if not provided
    if not name:
        name = Prompt.ask(
            "Session name",
            default="Coordination Session",
        )

    # Create the session
    try:
        session = CoordinationSession.create_session(deaddrop, name)
    except Exception as e:
        console.print(f"[red]Failed to create session: {e}[/red]")
        raise

    console.print(f"\n[green]✓ Session created: {session.session_id}[/green]")
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
        Optional[str],
        cyclopts.Parameter(help="Session ID to resume (interactive if not provided)"),
    ] = None,
):
    """Resume an existing coordination session.

    Reconnects to a previously created session and restarts the coordinator agent.
    If no session_id is provided, lists available sessions for selection.
    """
    console.print("\n[bold cyan]🤝 Resuming Coordination Session[/bold cyan]\n")

    # Ensure deaddrop is configured
    deaddrop = _ensure_deaddrop_configured()

    # If no session_id provided, show interactive selection
    if not session_id:
        sessions = list_sessions()

        if not sessions:
            console.print("[yellow]No saved sessions found.[/yellow]")
            console.print("[dim]Use 'silica coordinator new' to create one.[/dim]")
            return

        # Display sessions
        table = Table(title="Available Sessions", show_header=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Session ID", style="cyan")
        table.add_column("Name")
        table.add_column("Agents", justify="right")
        table.add_column("Created")

        for i, s in enumerate(sessions, 1):
            table.add_row(
                str(i),
                s["session_id"],
                s.get("display_name", ""),
                str(s.get("agent_count", 0)),
                s.get("created_at", "")[:10] if s.get("created_at") else "",
            )

        console.print(table)
        console.print()

        # Prompt for selection
        choice = Prompt.ask(
            "Select session number (or 'q' to quit)",
            default="1" if len(sessions) == 1 else None,
        )

        if choice.lower() == "q":
            console.print("[yellow]Cancelled[/yellow]")
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                session_id = sessions[idx]["session_id"]
            else:
                console.print("[red]Invalid selection[/red]")
                return
        except ValueError:
            # Maybe they typed the session ID directly
            session_id = choice

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
        raise

    state = session.get_state()
    console.print(f"[green]✓ Session resumed: {state['display_name']}[/green]")
    console.print(f"[dim]Session ID: {state['session_id']}[/dim]")
    console.print(f"[dim]Agents: {len(state.get('agents', {}))}[/dim]")
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
        Optional[str],
        cyclopts.Parameter(help="Session ID to delete"),
    ] = None,
    force: Annotated[
        bool,
        cyclopts.Parameter("--force", "-f", help="Skip confirmation"),
    ] = False,
):
    """Delete a saved coordination session."""
    # Interactive selection if no session_id
    if not session_id:
        sessions = list_sessions()

        if not sessions:
            console.print("[yellow]No sessions to delete.[/yellow]")
            return

        table = Table(title="Sessions", show_header=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Session ID", style="cyan")
        table.add_column("Name")

        for i, s in enumerate(sessions, 1):
            table.add_row(str(i), s["session_id"], s.get("display_name", ""))

        console.print(table)

        choice = Prompt.ask("Select session to delete (or 'q' to quit)")
        if choice.lower() == "q":
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                session_id = sessions[idx]["session_id"]
            else:
                console.print("[red]Invalid selection[/red]")
                return
        except ValueError:
            session_id = choice

    if not force:
        if not Confirm.ask(f"Delete session [cyan]{session_id}[/cyan]?", default=False):
            console.print("[yellow]Cancelled[/yellow]")
            return

    if delete_session(session_id):
        console.print(f"[green]✓ Session deleted: {session_id}[/green]")
    else:
        console.print(f"[red]Session not found: {session_id}[/red]")


@coordinator_app.command(name="info")
def coordinator_info(
    session_id: Annotated[
        Optional[str],
        cyclopts.Parameter(help="Session ID to inspect"),
    ] = None,
):
    """Show detailed information about a coordination session."""
    # Interactive selection if no session_id
    if not session_id:
        sessions = list_sessions()

        if not sessions:
            console.print("[yellow]No sessions found.[/yellow]")
            return

        if len(sessions) == 1:
            session_id = sessions[0]["session_id"]
        else:
            table = Table(show_header=True)
            table.add_column("#", style="dim", width=3)
            table.add_column("Session ID", style="cyan")
            table.add_column("Name")

            for i, s in enumerate(sessions, 1):
                table.add_row(str(i), s["session_id"], s.get("display_name", ""))

            console.print(table)

            choice = Prompt.ask("Select session", default="1")
            try:
                idx = int(choice) - 1
                session_id = sessions[idx]["session_id"]
            except (ValueError, IndexError):
                session_id = choice

    deaddrop = _ensure_deaddrop_configured()

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


# Default command shows help and options
@coordinator_app.default
def coordinator_default():
    """Interactive coordinator mode."""
    console.print("\n[bold cyan]🤝 Silica Coordinator[/bold cyan]\n")

    sessions = list_sessions()

    options = []
    if sessions:
        options.append(
            ("resume", f"Resume existing session ({len(sessions)} available)")
        )
    options.append(("new", "Create new coordination session"))
    options.append(("list", "List all sessions"))
    options.append(("quit", "Exit"))

    for i, (key, desc) in enumerate(options, 1):
        console.print(f"  [cyan]{i}[/cyan]. {desc}")

    console.print()
    choice = Prompt.ask("Select option", default="1" if sessions else "2")

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            action = options[idx][0]
        else:
            return
    except ValueError:
        action = choice.lower()

    if action == "resume":
        coordinator_resume()
    elif action == "new":
        coordinator_new()
    elif action == "list":
        coordinator_list()
    elif action == "quit":
        return
