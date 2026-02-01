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
        and summary statistics.
    """
    session = get_current_session()
    state = session.get_state()

    agents = state.get("agents", {})
    humans = state.get("humans", {})

    # Count agents by state
    state_counts = {}
    for agent in agents.values():
        s = agent.get("state", "unknown")
        state_counts[s] = state_counts.get(s, 0) + 1

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
