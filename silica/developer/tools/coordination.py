"""Coordinator tools for multi-agent orchestration.

These tools are available to the coordinator agent for managing
worker agents via deaddrop messaging.
"""

from typing import Optional

from silica.developer.coordination import (
    TaskAssign,
    Progress,
    PermissionResponse,
    Terminate,
)
from silica.developer.coordination.session import (
    CoordinationSession,
    AgentState,
)


# Global session reference - set by coordinator initialization
_current_session: Optional[CoordinationSession] = None


def set_current_session(session: CoordinationSession) -> None:
    """Set the current coordination session.

    Called by coordinator initialization to make the session
    available to coordinator tools.
    """
    global _current_session
    _current_session = session


def get_current_session() -> CoordinationSession:
    """Get the current coordination session.

    Raises:
        RuntimeError: If no session is active
    """
    if _current_session is None:
        raise RuntimeError("No coordination session active")
    return _current_session


# === Messaging Tools ===


def message_agent(
    agent_id: str,
    message_type: str,
    **kwargs,
) -> str:
    """Send a message to a specific agent.

    Args:
        agent_id: The agent to message
        message_type: Type of message ("task", "answer", "terminate")
        **kwargs: Message-specific parameters

    Returns:
        Confirmation message

    For task messages, include:
        - task_id: Unique task identifier
        - description: Task description
        - context: Optional dict with additional context
        - deadline: Optional deadline (ISO 8601)

    For answer messages, include:
        - question_id: ID of the question being answered
        - task_id: Associated task ID
        - answer: The answer text
        - context: Optional additional context

    For terminate messages, include:
        - reason: Optional reason for termination
    """
    session = get_current_session()
    agent = session.get_agent(agent_id)

    if not agent:
        return f"❌ Agent '{agent_id}' not found"

    # Build the appropriate message
    if message_type == "task":
        msg = TaskAssign(
            task_id=kwargs.get("task_id", ""),
            description=kwargs.get("description", ""),
            context=kwargs.get("context", {}),
            deadline=kwargs.get("deadline"),
        )
        # Update agent state
        session.update_agent_state(
            agent_id,
            AgentState.WORKING,
            task_id=kwargs.get("task_id"),
        )
    elif message_type == "terminate":
        msg = Terminate(reason=kwargs.get("reason"))
        session.update_agent_state(agent_id, AgentState.TERMINATED)
    else:
        return f"❌ Unknown message type: {message_type}"

    # Send via context
    session.context.send_message(agent.identity_id, msg)

    return f"✓ Sent {message_type} message to {agent.display_name} ({agent_id})"


def broadcast(
    message: str,
    message_type: str = "progress",
    **kwargs,
) -> str:
    """Broadcast a message to the coordination room.

    Args:
        message: The message content
        message_type: Type ("progress", "announcement")
        **kwargs: Additional fields

    Returns:
        Confirmation message
    """
    session = get_current_session()

    msg = Progress(
        task_id=kwargs.get("task_id", ""),
        agent_id="coordinator",
        message=message,
    )

    session.context.broadcast(msg)
    return f"✓ Broadcast: {message}"


def poll_messages(
    include_room: bool = True,
) -> str:
    """Check for new messages from agents.

    Checks the coordinator's inbox and optionally the coordination
    room for new messages. Returns immediately.

    Args:
        include_room: Whether to also check room messages

    Returns:
        Formatted list of received messages
    """
    session = get_current_session()
    messages = session.context.receive_messages(
        include_room=include_room,
    )

    if not messages:
        return "No new messages"

    lines = [f"**{len(messages)} new message(s):**\n"]

    for recv in messages:
        # Try to identify sender
        agent = session.get_agent_by_identity(recv.from_id)
        sender = agent.display_name if agent else recv.from_id[:8]

        # Update last_seen for known agents
        if agent:
            session.update_agent_last_seen(agent.agent_id)

        # Format based on message type
        msg = recv.message
        source = "(room)" if recv.is_room_message else "(direct)"

        msg_type = getattr(msg, "type", "unknown")
        lines.append(f"---\n**From:** {sender} {source}")
        lines.append(f"**Type:** {msg_type}")

        # Include relevant fields based on type
        if hasattr(msg, "agent_id") and msg.agent_id:
            lines.append(f"**Agent ID:** {msg.agent_id}")
        if hasattr(msg, "task_id") and msg.task_id:
            lines.append(f"**Task:** {msg.task_id}")
        if hasattr(msg, "status"):
            lines.append(f"**Status:** {msg.status}")
        if hasattr(msg, "message") and msg.message:
            lines.append(f"**Message:** {msg.message}")
        if hasattr(msg, "progress") and msg.progress is not None:
            lines.append(f"**Progress:** {msg.progress * 100:.0f}%")
        if hasattr(msg, "summary") and msg.summary:
            lines.append(f"**Summary:** {msg.summary}")
        if hasattr(msg, "question") and msg.question:
            lines.append(f"**Question:** {msg.question}")
        if hasattr(msg, "action") and msg.action:
            lines.append(f"**Action:** {msg.action}")
        if hasattr(msg, "resource") and msg.resource:
            lines.append(f"**Resource:** {msg.resource}")
        if hasattr(msg, "context") and isinstance(msg.context, str) and msg.context:
            lines.append(f"**Context:** {msg.context}")
        if hasattr(msg, "error") and msg.error:
            lines.append(f"**Error:** {msg.error}")

        lines.append("")

    return "\n".join(lines)


# === Agent Management Tools ===


def list_agents(
    state_filter: str = None,
    show_details: bool = False,
) -> str:
    """List all registered agents.

    Args:
        state_filter: Optional filter ("idle", "working", "spawning", etc.)
        show_details: Whether to include detailed info

    Returns:
        Formatted list of agents
    """
    session = get_current_session()

    filter_enum = None
    if state_filter:
        try:
            filter_enum = AgentState(state_filter)
        except ValueError:
            return f"❌ Invalid state filter: {state_filter}"

    agents = session.list_agents(state_filter=filter_enum)

    if not agents:
        return "No agents registered"

    lines = [f"**{len(agents)} agent(s):**\n"]

    for agent in agents:
        status_emoji = {
            AgentState.SPAWNING: "🔄",
            AgentState.STARTING: "⏳",
            AgentState.IDLE: "💤",
            AgentState.WORKING: "⚙️",
            AgentState.WAITING_PERMISSION: "🔒",
            AgentState.TERMINATED: "⏹️",
        }.get(agent.state, "❓")

        lines.append(
            f"- {status_emoji} **{agent.display_name}** ({agent.agent_id}): {agent.state.value}"
        )

        if show_details:
            lines.append(f"  - Workspace: {agent.workspace_name}")
            if agent.current_task_id:
                lines.append(f"  - Current task: {agent.current_task_id}")
            if agent.last_seen:
                lines.append(f"  - Last seen: {agent.last_seen}")

    return "\n".join(lines)


def get_session_state() -> str:
    """Get detailed information about the current coordination session.

    Returns:
        Formatted session state including namespace info, agent registry,
        pending permissions, and summary statistics.
    """
    session = get_current_session()
    state = session.get_state()

    agents = state.get("agents", {})
    humans = state.get("humans", {})
    pending_permissions = state.get("pending_permissions", {})

    # Count agents by state
    state_counts = {}
    for agent in agents.values():
        s = agent.get("state", "unknown")
        state_counts[s] = state_counts.get(s, 0) + 1

    # Count pending permissions by status
    pending_counts = {}
    for perm in pending_permissions.values():
        s = perm.get("status", "pending")
        pending_counts[s] = pending_counts.get(s, 0) + 1

    lines = [
        f"**Session:** {state['session_id']}",
        f"**Name:** {state.get('display_name', 'Unnamed')}",
        f"**Created:** {state['created_at']}",
        "",
        f"**Agents:** {len(agents)}",
    ]

    for s, count in state_counts.items():
        lines.append(f"  - {s}: {count}")

    lines.append(f"**Human participants:** {len(humans)}")

    # Show pending permissions if any
    if pending_permissions:
        lines.append("")
        lines.append(f"**Pending Permissions:** {len(pending_permissions)}")
        for s, count in pending_counts.items():
            lines.append(f"  - {s}: {count}")

    return "\n".join(lines)


def create_human_invite(
    display_name: str,
    expires_in: str = "24h",
) -> str:
    """Create an invite for a human to join the coordination session.

    Args:
        display_name: Name for the human participant
        expires_in: Invite expiration time (default: 24h)

    Returns:
        Invite URL and instructions
    """
    session = get_current_session()

    # Create identity for the human
    identity = session.deaddrop.create_identity(
        ns=session.namespace_id,
        display_name=display_name,
        ns_secret=session.namespace_secret,
    )

    # Register as human participant
    session.register_human(identity["id"], display_name)

    # Add to coordination room
    session.add_human_to_room(identity["id"])

    # TODO: When deaddrop supports invites, create a proper invite URL
    # For now, return the identity secret (requires secure sharing)

    return f"""**Human Invite Created**

**Name:** {display_name}
**Identity ID:** {identity["id"]}

To join, the human needs:
- Namespace: {session.namespace_id}
- Identity Secret: {identity["secret"]}
- Room ID: {session.state.room_id}

(Proper invite URLs coming in future deaddrop version)"""


# === Permission Tools ===


def grant_permission(
    request_id: str,
    decision: str,
    agent_id: str = None,
    reason: str = None,
) -> str:
    """Respond to a permission request from an agent.

    Args:
        request_id: The permission request ID
        decision: "allow" or "deny"
        agent_id: Optional agent ID (if not embedded in request_id)
        reason: Optional explanation

    Returns:
        Confirmation message
    """
    session = get_current_session()

    if decision not in ("allow", "deny"):
        return f"❌ Invalid decision: {decision}. Use 'allow' or 'deny'."

    # Find the agent that made the request
    # Try explicit agent_id first, then try parsing from request_id
    target_agent_id = agent_id
    if not target_agent_id and "-" in request_id:
        # The request_id format could be: "{agent_id}-{uuid}" or similar
        # Try the first segment
        potential_id = request_id.rsplit("-", 1)[0]
        if session.get_agent(potential_id):
            target_agent_id = potential_id
        else:
            # Try just the first part before any dash
            first_part = request_id.split("-")[0]
            if session.get_agent(first_part):
                target_agent_id = first_part

    agent = session.get_agent(target_agent_id) if target_agent_id else None

    if not agent:
        return f"❌ Cannot determine agent for request {request_id}. Specify agent_id."

    # Update agent state if they were waiting
    if agent.state == AgentState.WAITING_PERMISSION:
        session.update_agent_state(agent.agent_id, AgentState.WORKING)

    # Send permission response
    response = PermissionResponse(
        request_id=request_id,
        decision=decision,
        reason=reason,
    )

    session.context.send_message(agent.identity_id, response)

    return (
        f"✓ Sent {decision} for permission request {request_id} to {agent.display_name}"
    )


def escalate_to_user(
    request_id: str,
    context: str,
) -> str:
    """Escalate a permission request to a human participant.

    Args:
        request_id: The permission request ID
        context: Description of what's being requested and why

    Returns:
        Status message
    """
    session = get_current_session()
    humans = session.list_humans()

    if not humans:
        return (
            "⚠️ No human participants in session. "
            "Permission request queued. Use create_human_invite() to add a human."
        )

    # Send to all humans
    for human in humans:
        # Format as a question to the human
        from silica.developer.coordination import Question

        question = Question(
            question_id=request_id,
            task_id="",
            agent_id="coordinator",
            question=f"Permission Request: {context}\n\nAllow or deny?",
            options=["allow", "deny"],
        )
        session.context.send_message(human.identity_id, question)

    return f"✓ Escalated permission request to {len(humans)} human participant(s)"


# === Agent Spawning ===


def _get_project_repo_url() -> Optional[str]:
    """Get the repository URL for the current project.

    Returns:
        Git remote URL if available, None otherwise
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def _get_project_git_root() -> Optional[str]:
    """Get the git root directory for the current project.

    Returns:
        Path to git root if in a repository, None otherwise
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def _spawn_remote_worker(
    session: CoordinationSession,
    agent_id: str,
    workspace_name: str,
    display_name: str,
    invite_url: str,
    env_vars: dict,
    lines: list,
) -> str:
    """Spawn a worker in a remote silica workspace.

    Args:
        session: The coordination session
        agent_id: Assigned agent ID
        workspace_name: Name for the workspace
        display_name: Human-readable name for the worker
        invite_url: Deaddrop invite URL with coordination metadata
        env_vars: Environment variables for the worker
        lines: Output lines to append to

    Returns:
        Status message
    """
    import time
    from pathlib import Path

    lines.append("- Mode: REMOTE")

    # Get project info
    repo_url = _get_project_repo_url()
    git_root = _get_project_git_root()

    if not git_root:
        lines.extend(
            [
                "- State: FAILED",
                "",
                "**Failed:** Not in a git repository.",
                "Remote workers require a git repository to clone.",
            ]
        )
        session.update_agent_state(agent_id, AgentState.TERMINATED)
        return "\n".join(lines)

    if not repo_url:
        lines.extend(
            [
                "- State: FAILED",
                "",
                "**Failed:** No git remote 'origin' found.",
                "Remote workers require a repository URL to clone.",
            ]
        )
        session.update_agent_state(agent_id, AgentState.TERMINATED)
        return "\n".join(lines)

    # Find or create .silica directory
    silica_dir = Path(git_root) / ".silica"
    silica_dir.mkdir(exist_ok=True)

    # Check if workspace already exists and is healthy
    from silica.remote.config.multi_workspace import get_workspace_config

    existing_config = get_workspace_config(silica_dir, workspace_name)
    workspace_ready = False

    if existing_config and existing_config.get("url"):
        # Workspace exists, check if healthy
        lines.append(f"- Found existing workspace config: {workspace_name}")
        try:
            from silica.remote.utils.antennae_client import get_antennae_client

            client = get_antennae_client(silica_dir, workspace_name)
            success, _ = client.health_check()
            if success:
                workspace_ready = True
                lines.append("- Existing workspace is healthy, reusing")
        except Exception as e:
            lines.append(f"- Existing workspace unhealthy: {e}")

    if not workspace_ready:
        # Create the workspace
        lines.append(f"- Creating workspace: {workspace_name}")

        try:
            # Use silica remote create programmatically
            # For now, create a local workspace (--local 0 picks a free port)
            import subprocess

            # Find a free port
            import socket

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", 0))
                port = s.getsockname()[1]

            lines.append(f"- Using port: {port}")

            # Run silica remote create
            create_result = subprocess.run(
                [
                    "uv",
                    "run",
                    "silica",
                    "remote",
                    "create",
                    "-w",
                    workspace_name,
                    "--local",
                    str(port),
                    "--no-tools",  # Skip tool selection wizard
                ],
                cwd=git_root,
                capture_output=True,
                text=True,
                timeout=120,  # Workspace creation can take a while
            )

            if create_result.returncode != 0:
                lines.extend(
                    [
                        "- State: FAILED",
                        "",
                        f"**Failed to create workspace:** {create_result.stderr or create_result.stdout}",
                    ]
                )
                session.update_agent_state(agent_id, AgentState.TERMINATED)
                return "\n".join(lines)

            lines.append("- ✓ Workspace created")

            # Wait for antennae to be ready
            lines.append("- Waiting for antennae server...")

            from silica.remote.utils.antennae_client import get_antennae_client

            client = get_antennae_client(silica_dir, workspace_name)

            # Poll for health with retries
            for attempt in range(10):
                time.sleep(2)
                try:
                    success, _ = client.health_check()
                    if success:
                        workspace_ready = True
                        lines.append("- ✓ Antennae server ready")
                        break
                except Exception:
                    pass

            if not workspace_ready:
                lines.extend(
                    [
                        "- State: FAILED",
                        "",
                        "**Failed:** Antennae server did not become ready in time.",
                    ]
                )
                session.update_agent_state(agent_id, AgentState.TERMINATED)
                return "\n".join(lines)

            # Initialize the workspace (clone repo and start agent session)
            lines.append(f"- Initializing workspace with repo: {repo_url}")
            success, response = client.initialize(repo_url=repo_url, retries=3)

            if not success:
                error_msg = response.get(
                    "error", response.get("detail", "Unknown error")
                )
                lines.extend(
                    [
                        "- State: FAILED",
                        "",
                        f"**Failed to initialize workspace:** {error_msg}",
                    ]
                )
                session.update_agent_state(agent_id, AgentState.TERMINATED)
                return "\n".join(lines)

            lines.append("- ✓ Workspace initialized")

        except subprocess.TimeoutExpired:
            lines.extend(
                [
                    "- State: FAILED",
                    "",
                    "**Failed:** Workspace creation timed out.",
                ]
            )
            session.update_agent_state(agent_id, AgentState.TERMINATED)
            return "\n".join(lines)
        except Exception as e:
            lines.extend(
                [
                    "- State: FAILED",
                    "",
                    f"**Failed to create workspace:** {e}",
                ]
            )
            session.update_agent_state(agent_id, AgentState.TERMINATED)
            return "\n".join(lines)

    # Store workspace info in agent metadata
    session.update_agent_state(
        agent_id,
        AgentState.SPAWNING,
        remote_workspace=workspace_name,
    )

    # Now send the bootstrap message to the workspace
    from silica.developer.coordination.worker_bootstrap import (
        create_remote_worker_bootstrap_message,
    )

    bootstrap_message = create_remote_worker_bootstrap_message(
        invite_url=invite_url,
        agent_id=agent_id,
        display_name=display_name,
    )

    try:
        from silica.remote.utils.antennae_client import get_antennae_client

        client = get_antennae_client(silica_dir, workspace_name)

        success, response = client.tell(bootstrap_message)

        if success:
            lines.extend(
                [
                    "- ✓ Bootstrap message sent",
                    f"- Remote workspace: {workspace_name}",
                    "- State: SPAWNING → waiting for worker to connect",
                    "",
                    "**Worker launched in remote workspace!**",
                    "",
                    f"Workspace: {workspace_name}",
                    "",
                    "The worker should announce itself shortly. Use `list_agents` to check status.",
                ]
            )
        else:
            error_msg = response.get("error", "Unknown error")
            lines.extend(
                [
                    "- State: FAILED",
                    "",
                    f"**Failed to send bootstrap:** {error_msg}",
                ]
            )
            session.update_agent_state(agent_id, AgentState.TERMINATED)

    except Exception as e:
        lines.extend(
            [
                "- State: FAILED",
                "",
                f"**Failed to send bootstrap message:** {e}",
            ]
        )
        session.update_agent_state(agent_id, AgentState.TERMINATED)

    return "\n".join(lines)


def spawn_agent(
    workspace_name: str = None,
    display_name: str = None,
    remote: bool = False,
    cwd: str = None,
) -> str:
    """Create a new worker agent and launch it.

    This tool:
    1. Creates a deaddrop identity for the worker
    2. Registers the agent in the session
    3. Launches the worker in a tmux session (local mode) or via silica remote (remote mode)

    Args:
        workspace_name: Name for the worker's workspace (auto-generated if not provided)
        display_name: Human-readable name for the agent
        remote: Whether to deploy via silica remote (vs local tmux)
        cwd: Working directory for the worker (defaults to coordinator's cwd)

    Returns:
        Status of the spawned worker
    """
    import uuid
    import subprocess
    import os

    session = get_current_session()

    # Generate names if not provided
    if not workspace_name:
        workspace_name = f"worker-{uuid.uuid4().hex[:8]}"
    if not display_name:
        display_name = workspace_name.replace("-", " ").title()

    # Create identity for the worker
    worker_identity = session.deaddrop.create_identity(
        ns=session.namespace_id,
        display_name=display_name,
        ns_secret=session.namespace_secret,
    )

    # Generate agent ID
    agent_id = f"agent-{uuid.uuid4().hex[:8]}"

    # Register agent in session (state: SPAWNING)
    session.register_agent(
        agent_id=agent_id,
        identity_id=worker_identity["id"],
        display_name=display_name,
        workspace_name=workspace_name,
    )

    # Add agent to coordination room
    session.add_agent_to_room(agent_id)

    # Create a proper deaddrop invite URL for the worker
    invite = session.deaddrop.create_invite(
        ns=session.namespace_id,
        identity_id=worker_identity["id"],
        identity_secret=worker_identity["secret"],
        ns_secret=session.namespace_secret,
        display_name=f"Worker: {display_name}",
    )

    invite_url = invite["invite_url"]

    # Add coordination metadata as query parameters
    from urllib.parse import urlencode, urlparse, urlunparse

    parsed = urlparse(invite_url)
    coord_params = urlencode(
        {
            "room": session.state.room_id,
            "coordinator": session.state.coordinator_id,
        }
    )
    new_query = f"{parsed.query}&{coord_params}" if parsed.query else coord_params
    invite_url = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )

    # Environment variables for the worker
    env_vars = {
        "DEADDROP_INVITE_URL": invite_url,
        "COORDINATION_AGENT_ID": agent_id,
    }

    lines = [
        f"**Agent Created: {display_name}**",
        f"- Agent ID: {agent_id}",
        f"- Workspace: {workspace_name}",
    ]

    if remote:
        # Remote mode - use silica remote infrastructure
        return _spawn_remote_worker(
            session=session,
            agent_id=agent_id,
            workspace_name=workspace_name,
            display_name=display_name,
            invite_url=invite_url,
            env_vars=env_vars,
            lines=lines,
        )

    # Local mode - spawn worker directly in tmux
    tmux_session = f"worker-{agent_id}"

    # Store tmux session name in agent registration for later cleanup
    session.update_agent_state(
        agent_id,
        AgentState.SPAWNING,
        tmux_session=tmux_session,
    )

    # Build environment propagation
    # Copy important env vars from coordinator to worker
    from silica.remote.utils.github_auth import get_github_token

    propagate_vars = [
        "ANTHROPIC_API_KEY",
        "BRAVE_SEARCH_API_KEY",
    ]

    env_setup = []

    # Add coordination-specific env vars
    for key, value in env_vars.items():
        # Escape single quotes in value for shell
        escaped_value = value.replace("'", "'\\''")
        env_setup.append(f"export {key}='{escaped_value}'")

    # Add GitHub token
    github_token = get_github_token()
    if github_token:
        env_setup.append(f"export GH_TOKEN='{github_token}'")
        env_setup.append(f"export GITHUB_TOKEN='{github_token}'")

    # Propagate other important env vars
    for var in propagate_vars:
        value = os.environ.get(var)
        if value:
            escaped_value = value.replace("'", "'\\''")
            env_setup.append(f"export {var}='{escaped_value}'")

    env_setup_str = " && ".join(env_setup)

    # Build the worker launch command
    worker_dir = cwd if cwd else os.getcwd()
    worker_command = f"cd '{worker_dir}' && {env_setup_str} && uv run silica worker"

    try:
        # Create tmux session
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", tmux_session],
            check=True,
            capture_output=True,
        )

        # Give session a moment to initialize
        import time

        time.sleep(0.5)

        # Send the worker command to the session
        subprocess.run(
            ["tmux", "send-keys", "-t", tmux_session, worker_command, "C-m"],
            check=True,
            capture_output=True,
        )

        lines.extend(
            [
                "- Mode: LOCAL",
                f"- tmux session: `{tmux_session}`",
                "- State: SPAWNING → waiting for worker to connect",
                "",
                "**Worker launched successfully!**",
                "",
                f"View worker: `tmux attach -t {tmux_session}`",
                "",
                "The worker should announce itself shortly. Use `list_agents` to check status.",
            ]
        )

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        session.update_agent_state(agent_id, AgentState.TERMINATED)
        lines.extend(
            [
                "- State: FAILED",
                "",
                f"**Failed to launch worker:** {error_msg}",
            ]
        )
    except FileNotFoundError:
        session.update_agent_state(agent_id, AgentState.TERMINATED)
        lines.extend(
            [
                "- State: FAILED",
                "",
                "**Failed to launch worker:** tmux not found",
                "Please install tmux to spawn local workers.",
            ]
        )

    return "\n".join(lines)


def terminate_agent(
    agent_id: str,
    reason: str = None,
    destroy_workspace: bool = False,
) -> str:
    """Terminate a worker agent.

    Sends a termination message to the agent, kills its tmux session (if local)
    or sends termination to remote workspace, and updates its state.

    Args:
        agent_id: The agent to terminate
        reason: Optional reason for termination
        destroy_workspace: If True, destroy the remote workspace after termination

    Returns:
        Status message
    """
    import subprocess
    from pathlib import Path

    session = get_current_session()
    agent = session.get_agent(agent_id)

    if not agent:
        return f"❌ Agent '{agent_id}' not found"

    lines = [f"**Terminating agent: {agent.display_name} ({agent_id})**"]

    # Try to send termination message (may fail if agent already dead)
    try:
        msg = Terminate(reason=reason or "Terminated by coordinator")
        session.context.send_message(agent.identity_id, msg)
        lines.append("- ✓ Sent termination message via deaddrop")
    except Exception as e:
        lines.append(f"- ⚠ Could not send termination message: {e}")

    # Handle local worker (tmux session)
    tmux_session = getattr(agent, "tmux_session", None)
    if tmux_session:
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", tmux_session],
                check=True,
                capture_output=True,
            )
            lines.append(f"- ✓ Killed tmux session: {tmux_session}")
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            lines.append(f"- ⚠ Could not kill tmux session: {error_msg}")
        except FileNotFoundError:
            lines.append("- ⚠ tmux not available for session cleanup")

    # Handle remote worker (silica workspace)
    remote_workspace = getattr(agent, "remote_workspace", None)
    if remote_workspace:
        lines.append(f"- Remote workspace: {remote_workspace}")

        # Send termination message via antennae
        try:
            git_root = _get_project_git_root()
            if git_root:
                from silica.remote.utils.antennae_client import get_antennae_client
                from silica.developer.coordination.worker_bootstrap import (
                    create_worker_termination_message,
                )

                silica_dir = Path(git_root) / ".silica"
                client = get_antennae_client(silica_dir, remote_workspace)

                termination_msg = create_worker_termination_message(
                    agent_id=agent_id,
                    reason=reason,
                )

                success, _ = client.tell(termination_msg)
                if success:
                    lines.append("- ✓ Sent termination message to remote workspace")
                else:
                    lines.append("- ⚠ Could not send termination to workspace")
        except Exception as e:
            lines.append(f"- ⚠ Error sending termination to workspace: {e}")

        # Optionally destroy the workspace
        if destroy_workspace:
            try:
                result = subprocess.run(
                    [
                        "uv",
                        "run",
                        "silica",
                        "remote",
                        "destroy",
                        "-w",
                        remote_workspace,
                        "--force",
                    ],
                    cwd=git_root,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    lines.append(f"- ✓ Destroyed workspace: {remote_workspace}")
                else:
                    lines.append(f"- ⚠ Could not destroy workspace: {result.stderr}")
            except Exception as e:
                lines.append(f"- ⚠ Error destroying workspace: {e}")
        else:
            lines.append("- Workspace preserved (use destroy_workspace=True to remove)")

    if not tmux_session and not remote_workspace:
        lines.append("- No local or remote session to clean up")

    # Update state
    session.update_agent_state(agent_id, AgentState.TERMINATED)
    lines.append("- ✓ Agent state updated to TERMINATED")

    return "\n".join(lines)


# === Health Monitoring ===


def check_agent_health(
    stale_minutes: int = 10,
) -> str:
    """Check for stale or unhealthy agents.

    Args:
        stale_minutes: Minutes without activity to consider stale

    Returns:
        Health report for all agents
    """
    from datetime import datetime, timedelta

    session = get_current_session()
    agents = session.list_agents()

    if not agents:
        return "No agents to check"

    now = datetime.utcnow()
    stale_threshold = now - timedelta(minutes=stale_minutes)

    lines = ["**Agent Health Report:**\n"]
    healthy = 0
    stale = 0
    terminated = 0

    for agent in agents:
        if agent.state == AgentState.TERMINATED:
            terminated += 1
            continue

        if agent.last_seen:
            last_seen = datetime.fromisoformat(agent.last_seen.replace("Z", ""))
            if last_seen < stale_threshold:
                stale += 1
                minutes_ago = int((now - last_seen).total_seconds() / 60)
                lines.append(
                    f"⚠️ **{agent.display_name}** - stale ({minutes_ago} min ago)"
                )
            else:
                healthy += 1
                lines.append(f"✓ **{agent.display_name}** - healthy")
        else:
            # Never seen - check if recently created
            created = datetime.fromisoformat(agent.created_at.replace("Z", ""))
            if created < stale_threshold:
                stale += 1
                lines.append(f"⚠️ **{agent.display_name}** - never responded")
            else:
                healthy += 1
                lines.append(f"❓ **{agent.display_name}** - new (no messages yet)")

    lines.insert(1, f"Healthy: {healthy} | Stale: {stale} | Terminated: {terminated}\n")

    return "\n".join(lines)


# === Permission Queue ===


def list_pending_permissions(
    agent_id: str = None,
    status: str = None,
) -> str:
    """List pending permission requests in the queue.

    Permissions are queued when workers time out waiting for a response.
    The coordinator can later review and grant/deny them.

    Args:
        agent_id: Optional filter by agent ID
        status: Optional filter by status (pending, granted, denied, expired)

    Returns:
        Formatted list of pending permissions
    """
    session = get_current_session()
    pending = session.list_pending_permissions(agent_id=agent_id, status=status)

    if not pending:
        filter_desc = []
        if agent_id:
            filter_desc.append(f"agent={agent_id}")
        if status:
            filter_desc.append(f"status={status}")
        filter_str = f" (filter: {', '.join(filter_desc)})" if filter_desc else ""
        return f"No pending permissions{filter_str}"

    lines = [f"**Pending Permissions:** {len(pending)}\n"]

    for p in pending:
        lines.append(f"**Request:** {p.request_id}")
        lines.append(f"  - Agent: {p.agent_id}")
        lines.append(f"  - Action: {p.action}")
        lines.append(f"  - Resource: {p.resource}")
        lines.append(f"  - Status: {p.status}")
        lines.append(f"  - Requested: {p.requested_at}")
        if p.context:
            # Truncate context for display
            ctx = p.context[:200] + "..." if len(p.context) > 200 else p.context
            lines.append(f"  - Context: {ctx}")
        lines.append("")

    return "\n".join(lines)


def grant_queued_permission(
    request_id: str,
    decision: str = "allow",
    reason: str = None,
) -> str:
    """Grant or deny a queued permission request.

    After granting, the worker can be notified to retry the operation.

    Args:
        request_id: The permission request ID
        decision: "allow" or "deny"
        reason: Optional reason for the decision

    Returns:
        Confirmation message
    """
    session = get_current_session()
    pending = session.get_pending_permission(request_id)

    if not pending:
        return f"❌ Permission request '{request_id}' not found"

    if pending.status != "pending":
        return f"❌ Permission request '{request_id}' already {pending.status}"

    if decision not in ("allow", "deny"):
        return f"❌ Invalid decision: {decision}. Use 'allow' or 'deny'."

    # Update the status
    new_status = "granted" if decision == "allow" else "denied"
    session.update_pending_permission(request_id, new_status)

    # Get the agent
    agent = session.get_agent(pending.agent_id)
    if not agent:
        return (
            f"✓ Permission {new_status} (but agent '{pending.agent_id}' not found - "
            "cannot notify)"
        )

    # Send a PermissionResponse to the worker
    response = PermissionResponse(
        request_id=request_id,
        decision=decision,
        reason=reason,
    )

    try:
        session.context.send_message(agent.identity_id, response)
        return (
            f"✓ Permission {new_status} and notification sent to {agent.display_name}"
        )
    except Exception as e:
        return f"✓ Permission {new_status} but failed to notify agent: {e}"


def clear_expired_permissions(
    max_age_hours: int = 24,
) -> str:
    """Clear expired permission requests from the queue.

    Args:
        max_age_hours: Clear requests older than this many hours

    Returns:
        Number of permissions cleared
    """
    session = get_current_session()
    count = session.clear_expired_permissions(max_age_hours=max_age_hours)

    if count == 0:
        return "No expired permissions to clear"

    return f"✓ Marked {count} permission(s) as expired"
