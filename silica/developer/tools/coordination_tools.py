"""Coordination tool wrappers for the agent toolbox.

These are proper @tool-decorated functions that delegate to the
core coordination module. The context parameter is required by
the tool framework but not used (coordination uses a global session).
"""

from typing import TYPE_CHECKING

from .framework import tool

if TYPE_CHECKING:
    from silica.developer.context import AgentContext


@tool(group="coordination")
def spawn_agent(
    context: "AgentContext",
    workspace_name: str = None,
    display_name: str = None,
    remote: bool = False,
) -> str:
    """Create a new worker agent and launch it.

    This tool:
    1. Creates a deaddrop identity for the worker
    2. Registers the agent in the coordination session
    3. Launches the worker:
       - Local mode (remote=False): Worker runs in tmux session on same machine
       - Remote mode (remote=True): Worker runs in silica workspace (separate process)

    Args:
        workspace_name: Name for the worker's workspace (auto-generated if not provided)
        display_name: Human-readable name for the agent
        remote: If True, spawn worker in a silica workspace (provides process isolation).
                If False (default), spawn in a local tmux session.

    Returns:
        Status message about the spawned agent including:
        - Agent ID and workspace name
        - Spawning mode (LOCAL or REMOTE)
        - Connection status
    """
    from .coordination import spawn_agent as _spawn_agent

    return _spawn_agent(
        workspace_name=workspace_name,
        display_name=display_name,
        remote=remote,
    )


@tool(group="coordination")
def message_agent(
    context: "AgentContext",
    agent_id: str,
    message_type: str,
    task_id: str = "",
    description: str = "",
    task_context: dict = None,
    deadline: str = None,
    reason: str = None,
) -> str:
    """Send a message to a specific agent.

    Args:
        agent_id: The agent to message
        message_type: Type of message ("task", "answer", "terminate")
        task_id: Unique task identifier (for task messages)
        description: Task description (for task messages)
        task_context: Optional dict with additional context
        deadline: Optional deadline (ISO 8601)
        reason: Optional reason (for terminate messages)

    Returns:
        Confirmation message
    """
    from .coordination import message_agent as _message_agent

    return _message_agent(
        agent_id=agent_id,
        message_type=message_type,
        task_id=task_id,
        description=description,
        context=task_context or {},
        deadline=deadline,
        reason=reason,
    )


@tool(group="coordination")
def broadcast(
    context: "AgentContext",
    message: str,
    message_type: str = "progress",
    task_id: str = "",
) -> str:
    """Broadcast a message to the coordination room.

    Args:
        message: The message content
        message_type: Type ("progress", "announcement")
        task_id: Optional associated task ID

    Returns:
        Confirmation message
    """
    from .coordination import broadcast as _broadcast

    return _broadcast(
        message=message,
        message_type=message_type,
        task_id=task_id,
    )


@tool(group="coordination")
def poll_messages(
    context: "AgentContext",
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
    from .coordination import poll_messages as _poll_messages

    return _poll_messages(wait=wait, include_room=include_room)


@tool(group="coordination")
def list_agents(context: "AgentContext") -> str:
    """List all registered agents and their current state.

    Returns:
        Formatted table of agents with status
    """
    from .coordination import list_agents as _list_agents

    return _list_agents()


@tool(group="coordination")
def get_session_state(context: "AgentContext") -> str:
    """Get the full session state for debugging.

    Returns:
        JSON-formatted session state
    """
    from .coordination import get_session_state as _get_session_state

    return _get_session_state()


@tool(group="coordination")
def create_human_invite(
    context: "AgentContext",
    display_name: str = "Human Observer",
) -> str:
    """Create an invite link for a human to join the coordination session.

    Args:
        display_name: Name to display for this human

    Returns:
        Invite URL for the human to use
    """
    from .coordination import create_human_invite as _create_human_invite

    return _create_human_invite(display_name=display_name)


@tool(group="coordination")
def grant_permission(
    context: "AgentContext",
    permission_id: str,
    decision: str,
    reason: str = None,
) -> str:
    """Grant or deny a permission request from an agent.

    Args:
        permission_id: The ID of the permission request
        decision: "grant" or "deny"
        reason: Optional reason for the decision

    Returns:
        Confirmation message
    """
    from .coordination import grant_permission as _grant_permission

    return _grant_permission(
        permission_id=permission_id,
        decision=decision,
        reason=reason,
    )


@tool(group="coordination")
def escalate_to_user(
    context: "AgentContext",
    question: str,
    question_type: str = "question",
    options: list = None,
    task_id: str = None,
) -> str:
    """Escalate a question or decision to a human participant.

    Args:
        question: The question or decision to escalate
        question_type: Type ("question", "decision", "approval")
        options: List of valid options (if applicable)
        task_id: Associated task ID

    Returns:
        Escalation confirmation
    """
    from .coordination import escalate_to_user as _escalate_to_user

    return _escalate_to_user(
        question=question,
        question_type=question_type,
        options=options,
        task_id=task_id,
    )


@tool(group="coordination")
def terminate_agent(
    context: "AgentContext",
    agent_id: str,
    reason: str = None,
) -> str:
    """Terminate an agent's participation in the session.

    Args:
        agent_id: The agent to terminate
        reason: Optional reason for termination

    Returns:
        Confirmation message
    """
    from .coordination import terminate_agent as _terminate_agent

    return _terminate_agent(agent_id=agent_id, reason=reason)


@tool(group="coordination")
def check_agent_health(context: "AgentContext") -> str:
    """Check health of all agents by examining last_seen times.

    Returns:
        Health status report for all agents
    """
    from .coordination import check_agent_health as _check_agent_health

    return _check_agent_health()


@tool(group="coordination")
def list_pending_permissions(context: "AgentContext") -> str:
    """List all pending permission requests.

    Returns:
        Formatted list of pending permissions
    """
    from .coordination import list_pending_permissions as _list_pending_permissions

    return _list_pending_permissions()


@tool(group="coordination")
def grant_queued_permission(
    context: "AgentContext",
    request_id: str,
    decision: str,
    reason: str = None,
) -> str:
    """Grant or deny a queued permission request.

    Args:
        request_id: The ID of the permission request
        decision: "grant" or "deny"
        reason: Optional reason for the decision

    Returns:
        Confirmation message
    """
    from .coordination import grant_queued_permission as _grant_queued_permission

    return _grant_queued_permission(
        request_id=request_id,
        decision=decision,
        reason=reason,
    )


@tool(group="coordination")
def clear_expired_permissions(context: "AgentContext") -> str:
    """Clear expired permission requests.

    Returns:
        Number of expired requests cleared
    """
    from .coordination import clear_expired_permissions as _clear_expired_permissions

    return _clear_expired_permissions()


# Export all coordination tools
COORDINATION_TOOLS = [
    spawn_agent,
    message_agent,
    broadcast,
    poll_messages,
    list_agents,
    get_session_state,
    create_human_invite,
    grant_permission,
    escalate_to_user,
    terminate_agent,
    check_agent_health,
    list_pending_permissions,
    grant_queued_permission,
    clear_expired_permissions,
]
