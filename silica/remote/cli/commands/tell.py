"""Tell command for silica."""

import cyclopts
from typing import Annotated
from rich.console import Console

from silica.remote.config import find_git_root, get_silica_dir
from silica.remote.utils.antennae_client import get_antennae_client

console = Console()

# Prefix for coordinator mode messages
COORDINATOR_PREFIX = "coordinate:"


def _wrap_coordinator_message(goal: str) -> str:
    """Wrap a goal in coordinator mode instructions.

    Args:
        goal: The user's coordination goal

    Returns:
        Wrapped message with coordinator mode instructions
    """
    return f"""You are now operating in **Coordinator Mode** for multi-agent orchestration.

**Your Goal:** {goal}

**Coordinator Mode Instructions:**

1. **Use the coordinator tools** to spawn and manage worker agents:
   - `spawn_agent(workspace_name, display_name)` - Create new workers
   - `message_agent(agent_id, message_type, **kwargs)` - Send tasks
   - `poll_messages(wait)` - Receive updates from workers
   - `list_agents(filter_state)` - Check agent states
   - `terminate_agent(agent_id, reason)` - Clean up workers

2. **Break down the goal** into parallelizable tasks and assign to workers

3. **Monitor progress** by polling messages from workers

4. **Handle permission requests** from workers using:
   - `list_pending_permissions()` - View permission requests
   - `grant_queued_permission(request_id, decision)` - Allow/deny

5. **Coordinate results** and synthesize the final output

**Start by analyzing the goal and deciding how many workers you need.**
"""


def tell(
    *message: str,
    workspace: Annotated[
        str,
        cyclopts.Parameter(name=["--workspace", "-w"], help="Name for the workspace"),
    ] = "agent",
    coordinator: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--coordinator", "-c"],
            help="Start in coordinator mode (multi-agent orchestration)",
        ),
    ] = False,
):
    """Send a message to the agent via the antennae webapp.

    This command sends a message to the agent running in the workspace's tmux session
    via the antennae webapp's /tell endpoint.

    Messages can be sent in regular mode (default) or coordinator mode.
    Coordinator mode enables multi-agent orchestration where the agent can
    spawn and coordinate worker agents via deaddrop.

    Examples:
        silica remote tell "implement feature X"
        silica remote tell -c "build a web scraper with 3 parallel workers"
        silica remote tell "coordinate: review all PRs and summarize issues"

    The 'coordinate:' prefix in a message automatically enables coordinator mode.
    """
    try:
        # Get git root and silica dir
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        silica_dir = get_silica_dir()
        if not silica_dir or not (silica_dir / "config.yaml").exists():
            console.print(
                "[red]Error: No silica environment found in this repository.[/red]"
            )
            console.print(
                "Run [bold]silica remote create[/bold] to set up a workspace first."
            )
            return

        # Combine the message parts into a single string
        message_text = " ".join(message)

        if not message_text.strip():
            console.print("[red]Error: No message provided.[/red]")
            return

        # Check for coordinator mode prefix
        if message_text.lower().startswith(COORDINATOR_PREFIX):
            coordinator = True
            # Remove prefix from message
            message_text = message_text[len(COORDINATOR_PREFIX) :].strip()
            console.print("[cyan]Detected coordinator mode from message prefix[/cyan]")

        # Wrap message for coordinator mode
        if coordinator:
            message_text = _wrap_coordinator_message(message_text)

        # Get HTTP client for this workspace
        client = get_antennae_client(silica_dir, workspace)

        # Send the message via HTTP
        console.print(
            f"[green]Sending message to workspace '[bold]{workspace}[/bold]'[/green]"
        )
        console.print(f"[dim]Message: {message_text}[/dim]")

        success, response = client.tell(message_text)

        if success:
            console.print("[green]Message sent successfully.[/green]")
        else:
            error_msg = response.get("error", "Unknown error")
            detail = response.get("detail", "")
            console.print(f"[red]Error sending message: {error_msg}[/red]")
            if detail:
                console.print(f"[red]Detail: {detail}[/red]")

    except Exception as e:
        console.print(f"[red]Error sending message: {e}[/red]")
