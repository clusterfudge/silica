"""Worker CLI command.

Provides the `silica worker` command for running as a coordinated worker agent
that receives tasks from a coordinator via deaddrop.
"""

import asyncio
import os
from pathlib import Path
from typing import Optional, Annotated
from urllib.parse import urlparse, parse_qs

import cyclopts
from rich.console import Console
from rich.panel import Panel

from deadrop import Deaddrop

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from silica.developer.coordination import CoordinationContext

# Environment variable name for agent ID (matching worker_bootstrap)
COORDINATION_AGENT_ID_ENV = "COORDINATION_AGENT_ID"

console = Console()

# Create the worker app
worker_app = cyclopts.App(
    name="worker",
    help="Run as a coordinated worker agent",
)


def _parse_invite_url(invite_url: str) -> dict:
    """Parse a deaddrop invite URL to extract coordination metadata.

    The invite URL has the format:
    https://server/invite/...#key
    with query params: room=xxx&coordinator=xxx

    Returns:
        Dict with: server_url, room_id, coordinator_id, and the full invite URL
    """
    parsed = urlparse(invite_url)

    # Extract query parameters
    query_params = parse_qs(parsed.query)

    return {
        "server_url": f"{parsed.scheme}://{parsed.netloc}",
        "room_id": query_params.get("room", [None])[0],
        "coordinator_id": query_params.get("coordinator", [None])[0],
        "invite_url": invite_url,
    }


def _run_worker_agent(
    coord_context: "CoordinationContext",
    agent_id: str,
    working_dir: Path,
):
    """Run the worker agent loop.

    Sets up the worker persona and runs the agent loop to process
    tasks from the coordinator.
    """
    from silica.developer.agent_loop import run
    from silica.developer.context import AgentContext
    from silica.developer.models import get_model
    from silica.developer.sandbox import SandboxMode, Sandbox
    from silica.developer.hdev import CLIUserInterface
    from silica.developer.personas.worker_agent import (
        PERSONA as WORKER_PERSONA,
        MODEL,
    )

    # Import standard tool modules for workers
    from silica.developer.tools import ALL_TOOLS
    from silica.developer.utils import wrap_text_as_content_block
    from silica.developer.coordination import Idle, Progress
    from uuid import uuid4

    # Create user interface
    user_interface = CLIUserInterface(console, SandboxMode.ALLOW_ALL)

    # Get model spec
    model_spec = get_model(MODEL)

    # Create sandbox - workers run with ALLOW_ALL for now
    # TODO: Implement coordinator-routed permissions when deaddrop is more reliable
    sandbox = Sandbox(
        root_directory=str(working_dir),
        mode=SandboxMode.ALLOW_ALL,
        permission_check_callback=user_interface.permission_callback,
        permission_check_rendering_callback=user_interface.permission_rendering_callback,
    )

    # Set worker context for worker coordination tools
    from silica.developer.tools.worker_coordination import set_worker_context

    set_worker_context(coord_context, agent_id)

    # Create persona directory for history
    persona_dir = Path.home() / ".silica" / "personas" / "worker" / agent_id
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
    # Workers need dwr_mode=True to have tools available
    # (PermissionsManager filters all tools when dwr_mode=False and no permissions file)
    # But sandbox permissions still route to coordinator via setup_worker_sandbox_permissions
    context.dwr_mode = True

    # Store coordination info on context for tools to access
    context.coordination = {
        "coord_context": coord_context,
        "agent_id": agent_id,
        "room_id": coord_context.room_id,
        "coordinator_id": coord_context.coordinator_id,
    }

    # Announce ourselves to the coordinator
    console.print("[dim]Announcing to coordinator...[/dim]")

    try:
        # Send ready message to the coordination room
        ready_msg = Idle(
            agent_id=agent_id,
            completed_task_id=None,  # No task completed yet - just announcing
        )

        # Use coordination context to broadcast to room
        coord_context.broadcast(ready_msg)

        console.print("[green]✓ Announced to coordinator[/green]")
    except Exception as e:
        console.print(f"[red]Failed to announce: {e}[/red]")
        import traceback

        traceback.print_exc()
        # Continue anyway - coordinator may still be able to reach us

    # Display welcome
    console.print(
        Panel(
            f"[bold green]Worker Agent Active[/bold green]\n\n"
            f"Agent ID: {agent_id}\n"
            f"Model: {MODEL}\n"
            f"Working Directory: {working_dir}",
            title="🔧 Worker Mode",
        )
    )

    # Worker task processing loop
    # Poll for tasks from coordinator and execute them
    from silica.developer.coordination import (
        TaskAssign,
        Result,
    )

    task_count = 0

    while True:
        try:
            console.print("\n[dim]Waiting for task from coordinator...[/dim]")

            # Poll for messages (30 second timeout)
            messages = coord_context.receive_messages(wait=30, include_room=True)

            if not messages:
                continue

            # Find task assignment messages
            for msg_wrapper in messages:
                msg = msg_wrapper.message

                if isinstance(msg, TaskAssign):
                    task_count += 1
                    task_id = msg.task_id
                    description = msg.description
                    task_context = msg.context or {}

                    console.print(
                        f"\n[bold cyan]📋 Received Task: {task_id}[/bold cyan]"
                    )
                    console.print(f"[dim]{description}[/dim]")

                    # Send progress update
                    try:
                        coord_context.broadcast(
                            Progress(
                                task_id=task_id,
                                agent_id=agent_id,
                                status="working",
                                message="Starting task execution",
                                progress=0.0,
                            )
                        )
                    except Exception as e:
                        console.print(
                            f"[yellow]Warning: Could not send progress: {e}[/yellow]"
                        )

                    # Build prompt for this task
                    task_prompt = f"""**Task Assignment**
Task ID: {task_id}

**Instructions:**
{description}

**Context:**
{task_context if task_context else "No additional context provided."}

Execute this task now. When complete, clearly state "TASK COMPLETE" followed by a summary of what was accomplished."""

                    # Run the agent loop for this task
                    try:
                        asyncio.run(
                            run(
                                agent_context=context,
                                initial_prompt=task_prompt,
                                system_prompt=wrap_text_as_content_block(
                                    WORKER_PERSONA
                                ),
                                tools=ALL_TOOLS,  # Workers get all standard tools
                                single_response=False,  # Allow multi-turn for complex tasks
                            )
                        )

                        # Task completed (agent finished or user exited)
                        console.print(
                            f"\n[green]✓ Task {task_id} execution finished[/green]"
                        )

                        # Send completion
                        try:
                            coord_context.broadcast(
                                Result(
                                    task_id=task_id,
                                    agent_id=agent_id,
                                    status="completed",
                                    summary="Task executed by worker agent",
                                )
                            )
                        except Exception as e:
                            console.print(
                                f"[yellow]Warning: Could not send result: {e}[/yellow]"
                            )

                    except KeyboardInterrupt:
                        console.print("\n[yellow]Task interrupted[/yellow]")
                        try:
                            coord_context.broadcast(
                                Result(
                                    task_id=task_id,
                                    agent_id=agent_id,
                                    status="failed",
                                    summary="Task interrupted by user",
                                )
                            )
                        except Exception:
                            pass
                    except Exception as e:
                        console.print(f"\n[red]Task execution error: {e}[/red]")
                        try:
                            coord_context.broadcast(
                                Result(
                                    task_id=task_id,
                                    agent_id=agent_id,
                                    status="failed",
                                    summary=f"Error: {str(e)}",
                                )
                            )
                        except Exception:
                            pass

                    # Send idle status
                    try:
                        coord_context.broadcast(
                            Idle(
                                agent_id=agent_id,
                                completed_task_id=task_id,
                            )
                        )
                    except Exception:
                        pass

        except KeyboardInterrupt:
            console.print("\n[yellow]Worker shutting down...[/yellow]")
            break
        except Exception as e:
            console.print(f"\n[red]Error in task loop: {e}[/red]")
            import traceback

            traceback.print_exc()
            import time

            time.sleep(5)  # Wait before retrying


@worker_app.default
def worker_main(
    invite_url: Annotated[
        Optional[str],
        cyclopts.Parameter(
            name=["--invite-url", "-i"],
            help="Deaddrop invite URL (or set DEADDROP_INVITE_URL env var)",
        ),
    ] = None,
    agent_id: Annotated[
        Optional[str],
        cyclopts.Parameter(
            name=["--agent-id", "-a"],
            help="Agent ID (or set COORDINATION_AGENT_ID env var)",
        ),
    ] = None,
    working_dir: Annotated[
        Optional[str],
        cyclopts.Parameter(
            name=["--dir", "-d"],
            help="Working directory for file operations (default: current dir)",
        ),
    ] = None,
):
    """Start a worker agent that receives tasks from a coordinator.

    The worker connects to a coordination session using a deaddrop invite URL
    and waits for tasks from the coordinator.

    Environment variables:
        DEADDROP_INVITE_URL: The invite URL for connecting to the coordinator
        COORDINATION_AGENT_ID: The agent ID assigned by the coordinator
    """
    console.print("\n[bold cyan]🔧 Starting Worker Agent[/bold cyan]\n")

    # Get invite URL from env or parameter
    invite_url = invite_url or os.environ.get("DEADDROP_INVITE_URL")
    if not invite_url:
        console.print("[red]Error: No invite URL provided.[/red]")
        console.print("[dim]Set DEADDROP_INVITE_URL or use --invite-url[/dim]")
        return

    # Get agent ID from env or parameter
    agent_id = agent_id or os.environ.get("COORDINATION_AGENT_ID")
    if not agent_id:
        console.print("[red]Error: No agent ID provided.[/red]")
        console.print("[dim]Set COORDINATION_AGENT_ID or use --agent-id[/dim]")
        return

    # Parse invite URL for display
    invite_info = _parse_invite_url(invite_url)

    console.print(f"[dim]Agent ID: {agent_id}[/dim]")
    console.print(f"[dim]Room: {invite_info['room_id']}[/dim]")

    # Set agent ID in env for bootstrap to pick up
    os.environ[COORDINATION_AGENT_ID_ENV] = agent_id

    # Claim the invite and connect using the bootstrap module
    # This handles both local:// and https:// invite URLs
    try:
        from silica.developer.coordination.worker_bootstrap import (
            claim_invite_and_connect,
        )

        bootstrap_result = claim_invite_and_connect(invite_url=invite_url)
        coord_context = bootstrap_result.context

        console.print(
            f"[dim]Connected as identity: {coord_context.identity_id}[/dim]"
        )
        console.print("[green]✓ Connected to coordination session[/green]")
    except Exception as e:
        console.print(f"[red]Failed to connect to deaddrop: {e}[/red]")
        import traceback

        traceback.print_exc()
        return

    # Determine working directory
    work_dir = Path(working_dir) if working_dir else Path.cwd()
    work_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[dim]Working directory: {work_dir}[/dim]\n")

    # Run the worker agent
    _run_worker_agent(
        coord_context=coord_context,
        agent_id=agent_id,
        working_dir=work_dir,
    )
