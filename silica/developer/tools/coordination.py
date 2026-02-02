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
    wait: int = 30,
    include_room: bool = True,
) -> str:
    """Poll for new messages from agents.

    Long-polls the coordinator's inbox and optionally the coordination
    room for new messages.

    Args:
        wait: Timeout in seconds (0 for immediate return)
        include_room: Whether to also check room messages

    Returns:
        Formatted list of received messages
    """
    session = get_current_session()
    messages = session.context.receive_messages(
        wait=wait,
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
**Identity ID:** {identity['id']}

To join, the human needs:
- Namespace: {session.namespace_id}
- Identity Secret: {identity['secret']}
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


def spawn_agent(
    workspace_name: str = None,
    display_name: str = None,
    remote: bool = False,
) -> str:
    """Create a new worker agent identity and prepare for spawning.

    This tool:
    1. Creates a deaddrop identity for the worker
    2. Registers the agent in the session
    3. Returns spawn instructions with the invite URL

    The actual workspace creation should be done with `silica remote create`
    using the provided environment variables.

    Args:
        workspace_name: Name for the worker's workspace (auto-generated if not provided)
        display_name: Human-readable name for the agent
        remote: Whether this will be a remote workspace (vs local)

    Returns:
        Spawn instructions including environment variables to set
    """
    import uuid

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
    # The invite URL contains the server domain, so workers can connect without
    # needing a separate DEADDROP_URL environment variable
    invite = session.deaddrop.create_invite(
        ns=session.namespace_id,
        identity_id=worker_identity["id"],
        identity_secret=worker_identity["secret"],
        ns_secret=session.namespace_secret,
        display_name=f"Worker: {display_name}",
    )

    # The invite URL is the primary way to share credentials
    # We also include room_id and coordinator_id as query params for coordination
    invite_url = invite["invite_url"]

    # Add coordination metadata as query parameters
    # (These could also be stored on the server, but query params are simpler)
    from urllib.parse import urlencode, urlparse, urlunparse

    parsed = urlparse(invite_url)
    # Preserve the fragment (encryption key) while adding query params
    coord_params = urlencode(
        {
            "room": session.state.room_id,
            "coordinator": session.state.coordinator_id,
        }
    )
    # Combine with any existing query string
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

    # Build spawn instructions
    env_vars = {
        "DEADDROP_INVITE_URL": invite_url,
        "COORDINATION_AGENT_ID": agent_id,
    }

    lines = [
        f"**Agent Created: {display_name}**",
        f"- Agent ID: {agent_id}",
        f"- Workspace: {workspace_name}",
        "- State: SPAWNING",
        "",
        "**To spawn the worker, run:**",
        "```bash",
    ]

    if remote:
        lines.append(f"silica remote create -w {workspace_name} \\")
    else:
        lines.append(f"silica remote create -w {workspace_name} --local 0 \\")

    lines.append("  # Then set environment variables:")
    for key, value in env_vars.items():
        # Truncate long values for display
        display_value = value if len(value) < 60 else value[:57] + "..."
        lines.append(f"  # {key}={display_value}")

    lines.extend(
        [
            "```",
            "",
            "**Environment Variables (full):**",
        ]
    )

    for key, value in env_vars.items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(
        [
            "",
            "Once the workspace is created and the environment variables are set,",
            "the worker will automatically connect to this coordination session.",
        ]
    )

    return "\n".join(lines)


def terminate_agent(
    agent_id: str,
    reason: str = None,
) -> str:
    """Terminate a worker agent.

    Sends a termination message to the agent and updates its state.
    The workspace should be destroyed separately with `silica remote destroy`.

    Args:
        agent_id: The agent to terminate
        reason: Optional reason for termination

    Returns:
        Status message
    """
    session = get_current_session()
    agent = session.get_agent(agent_id)

    if not agent:
        return f"❌ Agent '{agent_id}' not found"

    # Send termination message
    msg = Terminate(reason=reason or "Terminated by coordinator")
    session.context.send_message(agent.identity_id, msg)

    # Update state
    session.update_agent_state(agent_id, AgentState.TERMINATED)

    lines = [
        f"✓ Terminated agent: {agent.display_name} ({agent_id})",
        "",
        "**To destroy the workspace:**",
        "```bash",
        f"silica remote destroy -w {agent.workspace_name}",
        "```",
    ]

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
