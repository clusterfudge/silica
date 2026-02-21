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


def _get_deaddrop_client(
    local: bool = False,
    remote: bool = False,
    local_path: Optional[str] = None,
    remote_url: Optional[str] = None,
):
    """Get a deaddrop client based on CLI flags.

    Priority:
    1. --local with optional --local-path -> LocalBackend
    2. --remote with optional --remote-url -> RemoteBackend
    3. Neither flag -> auto-discover from config

    Args:
        local: Use local .deaddrop backend
        remote: Use remote server backend
        local_path: Path to .deaddrop directory (optional, auto-discovers if not provided)
        remote_url: Remote server URL (optional, uses config if not provided)

    Returns:
        Configured Deaddrop client
    """
    from deadrop import Deaddrop
    from deadrop.config import GlobalConfig, init_wizard

    # Explicit local mode
    if local:
        if local_path:
            console.print(f"[dim]Using local deaddrop: {local_path}[/dim]")
            return Deaddrop.local(path=local_path)
        else:
            # Try to discover local .deaddrop
            try:
                client = Deaddrop.local()
                console.print(f"[dim]Using local deaddrop: {client.location}[/dim]")
                return client
            except Exception:
                # Create one in current directory
                console.print(
                    "[yellow]No local .deaddrop found. Creating one...[/yellow]"
                )
                client = Deaddrop.create_local()
                console.print(f"[green]Created: {client.location}[/green]")
                return client

    # Explicit remote mode
    if remote:
        if remote_url:
            # Use provided URL, still need token from config
            config = GlobalConfig.load() if GlobalConfig.exists() else None
            bearer_token = config.bearer_token if config else None
            console.print(f"[dim]Using remote deaddrop: {remote_url}[/dim]")
            return Deaddrop.remote(url=remote_url, bearer_token=bearer_token)
        else:
            # Use config
            if not GlobalConfig.exists():
                console.print("[yellow]Deaddrop not configured.[/yellow]")
                console.print("Let's set it up first.\n")
                init_wizard()
                console.print()
            config = GlobalConfig.load()
            console.print(f"[dim]Using remote deaddrop: {config.url}[/dim]")
            return Deaddrop.remote(url=config.url, bearer_token=config.bearer_token)

    # Auto-discover mode (default)
    # First check if there's a local .deaddrop in the project
    try:
        client = Deaddrop.local()
        console.print(f"[dim]Auto-discovered local deaddrop: {client.location}[/dim]")
        return client
    except Exception:
        pass

    # Fall back to remote config
    if not GlobalConfig.exists():
        console.print("[yellow]No deaddrop configuration found.[/yellow]")
        console.print()
        console.print("Options:")
        console.print("  1. Use --local to create a local .deaddrop in this directory")
        console.print("  2. Use --remote to configure a remote server")
        console.print()

        choice = Prompt.ask(
            "Setup mode",
            choices=["local", "remote"],
            default="local",
        )

        if choice == "local":
            client = Deaddrop.create_local()
            console.print(f"[green]Created local deaddrop: {client.location}[/green]")
            return client
        else:
            init_wizard()
            config = GlobalConfig.load()
            return Deaddrop.remote(url=config.url, bearer_token=config.bearer_token)

    config = GlobalConfig.load()
    console.print(f"[dim]Using remote deaddrop: {config.url}[/dim]")
    return Deaddrop.remote(url=config.url, bearer_token=config.bearer_token)


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
        cyclopts.Parameter(name=["--force", "-f"], help="Skip confirmation"),
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
    local: Annotated[
        bool,
        cyclopts.Parameter(name=["--local", "-l"], help="Use local .deaddrop backend"),
    ] = False,
    remote: Annotated[
        bool,
        cyclopts.Parameter(name=["--remote", "-r"], help="Use remote deaddrop server"),
    ] = False,
    local_path: Annotated[
        Optional[str],
        cyclopts.Parameter(
            name=["--local-path"], help="Path to local .deaddrop directory"
        ),
    ] = None,
    remote_url: Annotated[
        Optional[str],
        cyclopts.Parameter(name=["--remote-url"], help="Remote deaddrop server URL"),
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

    # Validate mutually exclusive flags
    if local and remote:
        console.print("[red]Cannot specify both --local and --remote[/red]")
        return

    deaddrop = _get_deaddrop_client(
        local=local,
        remote=remote,
        local_path=local_path,
        remote_url=remote_url,
    )

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
            f"Namespace: {state['namespace_id']}\n"
            f"Backend: {deaddrop.backend} ({deaddrop.location})",
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


@coordinator_app.command(name="init-local")
def coordinator_init_local(
    path: Annotated[
        Optional[str],
        cyclopts.Parameter(
            help="Directory to create .deaddrop in (default: current dir)"
        ),
    ] = None,
):
    """Initialize a local .deaddrop directory for coordination.

    Creates a .deaddrop directory with SQLite database for local-only
    coordination. Useful for development and single-machine workflows.
    """
    from deadrop import Deaddrop

    target_path = Path(path) if path else Path.cwd()

    # Check if already exists
    deaddrop_path = target_path / ".deaddrop"
    if deaddrop_path.exists():
        console.print(f"[yellow]Already exists: {deaddrop_path}[/yellow]")
        return

    try:
        client = Deaddrop.create_local(path=target_path)
        console.print(f"[green]✓ Created local deaddrop: {client.location}[/green]")
        console.print()
        console.print("[dim]Usage:[/dim]")
        console.print("  silica coordinator new --local")
        console.print("  silica coordinator resume --local")
    except Exception as e:
        console.print(f"[red]Failed to create local deaddrop: {e}[/red]")


def _run_coordinator_agent(
    session: CoordinationSession,
    persona: str | None = None,
    heartbeat_prompt: str | None = None,
    heartbeat_interval: int = 300,
):
    """Run the coordinator agent loop.

    Sets up the coordinator persona and runs the agent loop with
    coordination tools available.
    """
    from silica.developer.agent_loop import run
    from silica.developer.context import AgentContext
    from silica.developer.models import get_model
    from silica.developer.sandbox import SandboxMode
    from silica.developer.hdev import CLIUserInterface
    from silica.developer.personas.coordinator_agent import (
        PERSONA as COORDINATOR_PERSONA,
        TOOL_GROUPS,
        MODEL,
    )
    from silica.developer.tools.coordination_tools import COORDINATION_TOOLS
    from silica.developer.tools.files import (
        read_file,
        write_file,
        list_directory,
        edit_file,
    )
    from silica.developer.tools.planning import (
        enter_plan_mode,
        ask_clarifications,
        update_plan,
        add_plan_tasks,
        add_milestone,
        move_tasks_to_milestone,
        add_task_dependency,
        get_ready_tasks,
        expand_task,
        add_plan_metrics,
        define_metric_capture,
        capture_plan_metrics,
        read_plan,
        list_plans,
        exit_plan_mode,
        submit_for_approval,
        request_plan_approval,
        approve_plan,
        complete_plan_task,
        verify_plan_task,
        complete_plan,
    )
    from silica.developer.tools.memory import (
        get_memory_tree,
        search_memory,
        read_memory_entry,
        write_memory_entry,
        critique_memory,
        delete_memory_entry,
    )
    from silica.developer.tools.web import (
        web_search,
        safe_curl,
    )

    FILE_TOOLS = [
        read_file,
        write_file,
        list_directory,
        edit_file,
    ]

    PLANNING_TOOLS = [
        enter_plan_mode,
        ask_clarifications,
        update_plan,
        add_plan_tasks,
        add_milestone,
        move_tasks_to_milestone,
        add_task_dependency,
        get_ready_tasks,
        expand_task,
        add_plan_metrics,
        define_metric_capture,
        capture_plan_metrics,
        read_plan,
        list_plans,
        exit_plan_mode,
        submit_for_approval,
        request_plan_approval,
        approve_plan,
        complete_plan_task,
        verify_plan_task,
        complete_plan,
    ]

    MEMORY_TOOLS = [
        get_memory_tree,
        search_memory,
        read_memory_entry,
        write_memory_entry,
        critique_memory,
        delete_memory_entry,
    ]

    WEB_TOOLS = [
        web_search,
        safe_curl,
    ]
    from silica.developer.utils import wrap_text_as_content_block

    # Load heartbeat prompt from file if @file syntax
    heartbeat_prompt_text = None
    if heartbeat_prompt:
        if heartbeat_prompt.startswith("@"):
            prompt_path = Path(heartbeat_prompt[1:]).expanduser()
            if prompt_path.exists():
                heartbeat_prompt_text = prompt_path.read_text().strip()
            else:
                console.print(
                    f"[red]Heartbeat prompt file not found: {prompt_path}[/red]"
                )
                return
        else:
            heartbeat_prompt_text = heartbeat_prompt

    # Load persona if specified, otherwise use coordinator default
    persona_system_prompt = None
    persona_dir_path = None
    if persona:
        from silica.developer.personas import for_name as get_persona

        persona_obj = get_persona(persona)
        persona_system_prompt = persona_obj.system_block
        persona_dir_path = Path.home() / ".silica" / "personas" / persona
        persona_dir_path.mkdir(parents=True, exist_ok=True)

    # Set as current session for tools
    set_current_session(session)

    # Create user interface (CLI-only for coordinator)
    user_interface = CLIUserInterface(console, SandboxMode.ALLOW_ALL)

    # Get model spec (coordinator uses specified model, typically sonnet)
    model_spec = get_model(MODEL)

    # Create persona directory for history (use specified persona or coordinator default)
    persona_dir = (
        persona_dir_path
        if persona_dir_path
        else (Path.home() / ".silica" / "personas" / "coordinator")
    )
    persona_dir.mkdir(parents=True, exist_ok=True)

    # Use the coordination session ID as the silica session ID
    # This unifies coordinator sessions with silica sessions — one ID, one history
    session_id = session.session_id

    # Create context using standard AgentContext.create()
    # This handles session loading, history persistence, etc.
    context = AgentContext.create(
        model_spec=model_spec,
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=user_interface,
        session_id=session_id,
        persona_base_directory=persona_dir,
    )

    # Point the coordination session at the chat history directory
    # so coordination.json lives alongside the conversation
    session.history_dir = context._get_history_dir()
    session.save_state()

    # Coordinator uses DWR mode to bypass permissions for coordination tools
    context.dwr_mode = True

    # Build initial prompt — minimal context, no tool listing
    state = session.get_state()
    agents = state.get("agents", {})
    backend_info = f"{session.deaddrop.backend} ({session.deaddrop.location})"

    if agents:
        # Resumed session with existing agents — give status summary
        agent_lines = []
        for aid, a in agents.items():
            agent_lines.append(
                f"  - {aid}: {a.get('display_name', '?')} ({a.get('state', 'unknown')})"
            )
        agent_summary = "\n".join(agent_lines)
        initial_prompt = (
            f"[Coordination session resumed: {state['display_name']}]\n"
            f"Session ID: {session.session_id}\n"
            f"Backend: {backend_info}\n\n"
            f"Active agents:\n{agent_summary}\n\n"
            f"Check for pending messages and pick up where we left off."
        )
    else:
        # Fresh session — don't trigger discovery
        initial_prompt = (
            f"[New coordination session: {state['display_name']}]\n"
            f"Session ID: {session.session_id}\n"
            f"Backend: {backend_info}\n\n"
            f"No agents yet. Ready for instructions."
        )

    # Display welcome
    persona_label = persona if persona else "coordinator"
    heartbeat_label = f"{heartbeat_interval}s" if heartbeat_prompt_text else "off"
    console.print(
        Panel(
            f"[bold green]Coordinator Agent Active[/bold green]\n\n"
            f"Session: {session.session_id}\n"
            f"Backend: {backend_info}\n"
            f"Persona: {persona_label}\n"
            f"Model: {MODEL}\n"
            f"Heartbeat: {heartbeat_label}\n"
            f"Tools: {', '.join(TOOL_GROUPS)}",
            title="🤝 Coordination Mode",
        )
    )

    # Build system prompt: persona + coordinator capability overlay
    if persona_system_prompt:
        # Compose: persona identity + coordinator tools/protocol
        system_prompt = persona_system_prompt
    else:
        system_prompt = wrap_text_as_content_block(COORDINATOR_PERSONA)

    # Set terminal tab title
    from silica.developer.utils import set_terminal_title, restore_terminal_title

    coordinator_label = f"coordinator:{persona}" if persona else "coordinator"
    set_terminal_title(persona=coordinator_label)

    import atexit

    atexit.register(restore_terminal_title)

    # Run the agent loop with coordination session for real-time message handling
    try:
        asyncio.run(
            run(
                agent_context=context,
                initial_prompt=initial_prompt,
                single_response=False,
                system_prompt=system_prompt,
                tools=COORDINATION_TOOLS
                + PLANNING_TOOLS
                + FILE_TOOLS
                + MEMORY_TOOLS
                + WEB_TOOLS,
                heartbeat_prompt=heartbeat_prompt_text,
                heartbeat_idle_seconds=heartbeat_interval,
                coordination_session=session,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Coordinator session ended.[/yellow]")
    finally:
        set_current_session(None)
        # Print resume command
        import sys

        cmd_parts = ["silica", "coordinator", "--session-id", session.session_id]
        if persona:
            cmd_parts.extend(["--persona", persona])
        resume_cmd = " ".join(cmd_parts)
        print(
            "\n\033[2m# To resume this session:\033[0m",
            file=sys.stderr,
        )
        print(f"\033[36m{resume_cmd}\033[0m", file=sys.stderr)


# Default command shows help and options
@coordinator_app.default
def coordinator_default(
    name: Annotated[
        Optional[str],
        cyclopts.Parameter(help="Display name for the coordination session"),
    ] = None,
    session_id: Annotated[
        Optional[str],
        cyclopts.Parameter(
            name=["--session-id"],
            help="Session ID to resume (creates new if not found)",
        ),
    ] = None,
    local: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--local", "-l"], help="Use local .deaddrop backend (no network)"
        ),
    ] = False,
    remote: Annotated[
        bool,
        cyclopts.Parameter(name=["--remote", "-r"], help="Use remote deaddrop server"),
    ] = False,
    local_path: Annotated[
        Optional[str],
        cyclopts.Parameter(
            name=["--local-path"], help="Path to local .deaddrop directory"
        ),
    ] = None,
    remote_url: Annotated[
        Optional[str],
        cyclopts.Parameter(name=["--remote-url"], help="Remote deaddrop server URL"),
    ] = None,
    persona: Annotated[
        Optional[str],
        cyclopts.Parameter(help="Persona to overlay on coordinator (e.g., twin)"),
    ] = None,
    heartbeat_prompt: Annotated[
        Optional[str],
        cyclopts.Parameter(
            name=["--heartbeat-prompt"],
            help="Heartbeat prompt file or text. Supports @file syntax. Enables daemon mode.",
        ),
    ] = None,
    heartbeat_interval: Annotated[
        int,
        cyclopts.Parameter(
            name=["--heartbeat-interval"],
            help="Seconds of idle before heartbeat fires (default: 300)",
        ),
    ] = 300,
):
    """Start or resume a coordination session.

    If --session-id is provided, resumes that session (or creates it if new).
    If no --session-id, creates a fresh session.

    Backend options:
      --local, -l       Use local .deaddrop (no network, single machine)
      --remote, -r      Use remote deaddrop server (distributed workers)
    """
    if local and remote:
        console.print("[red]Cannot specify both --local and --remote[/red]")
        return

    deaddrop = _get_deaddrop_client(
        local=local,
        remote=remote,
        local_path=local_path,
        remote_url=remote_url,
    )
    console.print()

    # Compute history dir for session lookup
    if persona:
        from silica.developer.personas import for_name as _get_persona_default

        _p = _get_persona_default(persona)
        _persona_dir = _p.base_directory
    else:
        _persona_dir = Path.home() / ".silica" / "personas" / "coordinator"

    # If session_id provided, try to resume
    if session_id:
        _hdir = _persona_dir / "history" / session_id
        _coord_file = _hdir / "coordination.json"
        from silica.developer.coordination.session import get_sessions_dir

        _legacy_file = get_sessions_dir() / f"{session_id}.json"

        if _coord_file.exists() or _legacy_file.exists():
            console.print("[bold cyan]🤝 Resuming Coordination Session[/bold cyan]\n")
            try:
                session = CoordinationSession.resume_session(
                    deaddrop, session_id=session_id, history_dir=_hdir
                )
            except Exception as e:
                console.print(f"[red]Failed to resume session: {e}[/red]")
                raise

            state = session.get_state()
            console.print(f"[green]✓ Session resumed: {state['display_name']}[/green]")
            console.print(f"[dim]Session ID: {session_id}[/dim]")
            console.print(
                f"[dim]Backend: {deaddrop.backend} ({deaddrop.location})[/dim]"
            )
            console.print()

            _run_coordinator_agent(
                session,
                persona=persona,
                heartbeat_prompt=heartbeat_prompt,
                heartbeat_interval=heartbeat_interval,
            )
            return

    # Create new session
    console.print("[bold cyan]🤝 Creating Coordination Session[/bold cyan]\n")

    if not name:
        name = session_id or "Coordination Session"

    from uuid import uuid4 as _uuid4

    new_session_id = session_id or str(_uuid4())

    try:
        session = CoordinationSession.create_session(
            deaddrop, name, session_id=new_session_id
        )
    except Exception as e:
        console.print(f"[red]Failed to create session: {e}[/red]")
        raise

    console.print(f"[green]✓ Session created: {session.session_id}[/green]")
    console.print(f"[dim]Namespace: {session.namespace_id}[/dim]")
    console.print(f"[dim]Backend: {deaddrop.backend} ({deaddrop.location})[/dim]")
    console.print()

    _run_coordinator_agent(
        session,
        persona=persona,
        heartbeat_prompt=heartbeat_prompt,
        heartbeat_interval=heartbeat_interval,
    )
