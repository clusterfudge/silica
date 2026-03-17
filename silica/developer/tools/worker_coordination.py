"""Worker coordination tools for communicating with the coordinator.

These tools are available to worker agents spawned by a coordinator.
Workers use these to receive tasks, report progress, and request permissions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional
import time
import uuid

if TYPE_CHECKING:
    from silica.developer.context import AgentContext

from silica.developer.coordination import (
    CoordinationContext,
    TaskAck,
    Progress,
    Result,
    PermissionRequest,
    PermissionResponse,
    Idle,
    Question,
    MessageType,
)


# Global context reference - set by worker bootstrap
_worker_context: Optional[CoordinationContext] = None
_worker_agent_id: Optional[str] = None
_current_task_id: Optional[str] = None


def set_worker_context(
    context: CoordinationContext,
    agent_id: str,
) -> None:
    """Set the worker's coordination context.

    Called by worker bootstrap to make the context available to tools.
    """
    global _worker_context, _worker_agent_id
    _worker_context = context
    _worker_agent_id = agent_id


def get_worker_context() -> CoordinationContext:
    """Get the worker's coordination context.

    Raises:
        RuntimeError: If not running as a coordinated worker
    """
    if _worker_context is None:
        raise RuntimeError(
            "Not running as a coordinated worker. Worker context not initialized."
        )
    return _worker_context


def get_worker_agent_id() -> str:
    """Get this worker's agent ID."""
    if _worker_agent_id is None:
        raise RuntimeError("Worker agent ID not set")
    return _worker_agent_id


def set_current_task(task_id: str) -> None:
    """Set the current task ID being worked on."""
    global _current_task_id
    _current_task_id = task_id


def get_current_task() -> Optional[str]:
    """Get the current task ID."""
    return _current_task_id


# === Inbox Tools ===


def check_inbox(context: "AgentContext" = None) -> str:
    """Check for new messages from the coordinator.

    Returns immediately with any new messages since the last check.

    Returns:
        Formatted list of messages or "No new messages"
    """
    ctx = get_worker_context()
    messages = ctx.receive_messages(include_room=False)

    if not messages:
        return "No new messages"

    lines = [f"**{len(messages)} new message(s):**\n"]

    for recv in messages:
        msg = recv.message
        msg_type = getattr(msg, "type", "unknown")

        lines.append("---")
        lines.append(f"**Type:** {msg_type}")

        # Handle different message types
        if msg_type == MessageType.TASK_ASSIGN.value:
            lines.append(f"**Task ID:** {msg.task_id}")
            lines.append(f"**Description:** {msg.description}")
            if msg.context:
                lines.append(f"**Context:** {msg.context}")
            if msg.deadline:
                lines.append(f"**Deadline:** {msg.deadline}")

        elif msg_type == MessageType.PERMISSION_RESPONSE.value:
            lines.append(f"**Request ID:** {msg.request_id}")
            lines.append(f"**Decision:** {msg.decision}")
            if msg.reason:
                lines.append(f"**Reason:** {msg.reason}")

        elif msg_type == MessageType.ANSWER.value:
            lines.append(f"**Question ID:** {msg.question_id}")
            lines.append(f"**Answer:** {msg.answer}")
            if msg.context:
                lines.append(f"**Context:** {msg.context}")

        elif msg_type == MessageType.TERMINATE.value:
            lines.append("**⚠️ TERMINATION REQUESTED**")
            if msg.reason:
                lines.append(f"**Reason:** {msg.reason}")

        lines.append("")

    return "\n".join(lines)


# === Communication Tools ===


def send_to_coordinator(
    context: "AgentContext" = None,
    message_type: str = "",
    task_id: str = "",
    status: str = "complete",
    summary: str = "",
    data: Optional[dict] = None,
    error: str = "",
    progress: Optional[float] = None,
    message: str = "",
    question: str = "",
    options: Optional[list] = None,
    **kwargs,
) -> str:
    """Send a message to the coordinator.

    Args:
        message_type: Type of message - "result", "ack", "progress", or "question"
        task_id: ID of the task (auto-detected if omitted)
        status: Result status - "complete", "failed", "blocked", "partial" (for result messages)
        summary: Brief summary of work done (for result messages)
        data: Optional dict with structured results (for result messages)
        error: Error message if status is "failed" (for result messages)
        progress: Progress value 0.0 to 1.0 (for progress messages)
        message: Status message (for progress messages)
        question: The question text (for question messages)
        options: List of predefined options (for question messages)

    Returns:
        Confirmation message
    """
    # Backward compat: direct calls pass message_type as first positional arg
    # e.g. send_to_coordinator("result", summary="...") where "result" fills context
    if isinstance(context, str) and context:
        message_type = context

    # Handle Claude sending "type" instead of "message_type"
    if not message_type:
        message_type = kwargs.get("type", "")

    ctx = get_worker_context()
    agent_id = get_worker_agent_id()

    resolved_task_id = task_id or get_current_task() or ""

    if message_type == "ack":
        msg = TaskAck(task_id=resolved_task_id, agent_id=agent_id)
        set_current_task(resolved_task_id)

    elif message_type == "progress":
        msg = Progress(
            task_id=resolved_task_id,
            agent_id=agent_id,
            progress=progress,
            message=message,
        )

    elif message_type == "result":
        msg = Result(
            task_id=resolved_task_id,
            agent_id=agent_id,
            status=status,
            summary=summary,
            data=data or {},
            error=error or None,
        )
        # Clear current task after sending result
        if resolved_task_id == get_current_task():
            set_current_task(None)

    elif message_type == "question":
        question_id = kwargs.get("question_id", f"q-{uuid.uuid4().hex[:8]}")
        msg = Question(
            question_id=question_id,
            task_id=resolved_task_id,
            agent_id=agent_id,
            question=question,
            options=options or [],
        )

    else:
        return f"❌ Unknown message type: {message_type!r}. Use 'result', 'ack', 'progress', or 'question'."

    ctx.send_to_coordinator(msg)
    return f"✓ Sent {message_type} to coordinator"


def broadcast_status(
    context: "AgentContext" = None,
    message: str = "",
    progress: float = None,
) -> str:
    """Broadcast a status update to the coordination room.

    Args:
        message: Status message
        progress: Optional progress value (0.0 to 1.0)

    Returns:
        Confirmation message
    """
    ctx = get_worker_context()
    agent_id = get_worker_agent_id()

    msg = Progress(
        task_id=get_current_task() or "",
        agent_id=agent_id,
        progress=progress,
        message=message,
    )

    ctx.broadcast(msg)
    return f"✓ Broadcast: {message}"


def mark_idle(context: "AgentContext" = None) -> str:
    """Signal that this worker is idle and available for tasks.

    Call this after completing a task to indicate readiness for more work.

    Returns:
        Confirmation message
    """
    ctx = get_worker_context()
    agent_id = get_worker_agent_id()

    msg = Idle(
        agent_id=agent_id,
        completed_task_id=get_current_task(),
    )

    # Clear current task
    set_current_task(None)

    ctx.broadcast(msg)
    return "✓ Marked as idle and available for tasks"


# === Permission Tools ===


def request_permission(
    context: "AgentContext" = None,
    action: str = "",
    resource: str = "",
    reason: str = "",
    timeout: int = 300,
) -> str:
    """Request permission from the coordinator for a sensitive operation.

    This will block waiting for the coordinator's response.

    Args:
        action: Type of action (e.g., "shell_execute", "write_file")
        resource: The resource being accessed (e.g., command, file path)
        reason: Human-readable explanation of why this is needed
        timeout: Max seconds to wait for response (default: 5 min)

    Returns:
        Decision string: "allow", "deny", or "timeout"
    """
    ctx = get_worker_context()
    agent_id = get_worker_agent_id()

    request_id = f"{agent_id}-perm-{uuid.uuid4().hex[:8]}"

    # Send permission request
    request = PermissionRequest(
        request_id=request_id,
        task_id=get_current_task() or "",
        agent_id=agent_id,
        action=action,
        resource=resource,
        context=reason,
    )

    ctx.send_to_coordinator(request)

    # Wait for response using subscriptions (wakes instantly on publish)
    start_time = time.time()

    while (time.time() - start_time) < timeout:
        remaining = timeout - (time.time() - start_time)
        if remaining <= 0:
            break
        messages = ctx.wait_for_messages(timeout=min(remaining, 30), include_room=False)

        for recv in messages:
            msg = recv.message
            if isinstance(msg, PermissionResponse) and msg.request_id == request_id:
                return msg.decision

    return "timeout"


def request_permission_async(
    context: "AgentContext" = None,
    action: str = "",
    resource: str = "",
    reason: str = "",
) -> str:
    """Request permission without blocking.

    Use this when you want to continue with other work while
    waiting for permission. Check inbox later for the response.

    Args:
        action: Type of action
        resource: Resource being accessed
        reason: Explanation of why this is needed

    Returns:
        Request ID to track the permission request
    """
    ctx = get_worker_context()
    agent_id = get_worker_agent_id()

    request_id = f"{agent_id}-perm-{uuid.uuid4().hex[:8]}"

    request = PermissionRequest(
        request_id=request_id,
        task_id=get_current_task() or "",
        agent_id=agent_id,
        action=action,
        resource=resource,
        context=reason,
    )

    ctx.send_to_coordinator(request)

    return f"✓ Permission request sent (ID: {request_id}). Check inbox for response."


# === Agent-to-Agent Communication Tools ===


def list_workers(context: "AgentContext" = None) -> str:
    """List other workers in this coordination session.

    Returns information about other workers you can communicate with.

    Returns:
        Formatted list of workers with their IDs and status
    """
    ctx = get_worker_context()
    get_worker_agent_id()

    # Get room members from the coordination room
    # Workers can see who else is in the room
    try:
        room_members = ctx.deaddrop.list_room_members(
            ns=ctx.namespace_id,
            room_id=ctx.room_id,
            secret=ctx.identity_secret,
        )
    except Exception as e:
        return f"❌ Could not list workers: {e}"

    if not room_members:
        return "No other workers found in this session."

    lines = [f"**{len(room_members)} participant(s) in coordination room:**\n"]

    for member in room_members:
        member_id = member.get("identity_id", "unknown")
        display_name = member.get("display_name", member_id[:8])

        # Mark self
        if member_id == ctx.identity_id:
            lines.append(f"- **{display_name}** ({member_id[:8]}...) ← you")
        elif member_id == ctx.coordinator_id:
            lines.append(f"- **{display_name}** ({member_id[:8]}...) [coordinator]")
        else:
            lines.append(f"- **{display_name}** ({member_id[:8]}...)")

    return "\n".join(lines)


def send_to_worker(
    context: "AgentContext" = None,
    worker_id: str = "",
    message: str = "",
    message_type: str = "text",
) -> str:
    """Send a direct message to another worker.

    Args:
        worker_id: The identity ID of the worker (or partial ID prefix)
        message: The message content
        message_type: Type of message ("text", "json", or custom)

    Returns:
        Confirmation or error message
    """
    ctx = get_worker_context()
    agent_id = get_worker_agent_id()

    # Resolve partial worker ID if needed
    if len(worker_id) < 16:
        # Try to find matching worker in room
        try:
            room_members = ctx.deaddrop.list_room_members(
                ns=ctx.namespace_id,
                room_id=ctx.room_id,
                secret=ctx.identity_secret,
            )
            matches = [
                m
                for m in room_members
                if m.get("identity_id", "").startswith(worker_id)
            ]
            if len(matches) == 1:
                worker_id = matches[0]["identity_id"]
            elif len(matches) > 1:
                return (
                    f"❌ Ambiguous worker ID '{worker_id}' - matches multiple workers"
                )
            else:
                return f"❌ No worker found matching '{worker_id}'"
        except Exception:
            pass  # Fall through and try the ID as-is

    # Build message body
    import json

    body = json.dumps(
        {
            "type": message_type,
            "from_agent": agent_id,
            "content": message,
        }
    )

    try:
        ctx.deaddrop.send_message(
            ns=ctx.namespace_id,
            to_id=worker_id,
            body=body,
            from_secret=ctx.identity_secret,
            content_type="application/vnd.silica.worker-message+json",
        )
        return f"✓ Message sent to {worker_id[:8]}..."
    except Exception as e:
        return f"❌ Failed to send message: {e}"


def create_collaboration_room(
    context: "AgentContext" = None,
    name: str = "",
    invite_workers: list[str] = None,
) -> str:
    """Create a room for collaborating with other workers.

    Use this when you need to coordinate with specific workers on a sub-task.
    You can invite other workers to the room.

    Args:
        name: Display name for the room
        invite_workers: Optional list of worker identity IDs to invite

    Returns:
        Room ID and confirmation, or error message
    """
    ctx = get_worker_context()

    try:
        room = ctx.deaddrop.create_room(
            ns=ctx.namespace_id,
            creator_secret=ctx.identity_secret,
            display_name=name,
        )
        room_id = room["room_id"]

        lines = [f"✓ Created room: **{name}**", f"  Room ID: {room_id}"]

        # Invite workers if specified
        if invite_workers:
            for worker_id in invite_workers:
                try:
                    ctx.deaddrop.add_room_member(
                        ns=ctx.namespace_id,
                        room_id=room_id,
                        identity_id=worker_id,
                        secret=ctx.identity_secret,
                    )
                    lines.append(f"  ✓ Invited {worker_id[:8]}...")
                except Exception as e:
                    lines.append(f"  ❌ Failed to invite {worker_id[:8]}...: {e}")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to create room: {e}"


def invite_to_room(
    context: "AgentContext" = None,
    room_id: str = "",
    worker_id: str = "",
) -> str:
    """Invite another worker to a room you're a member of.

    Args:
        room_id: The room to invite to
        worker_id: The worker's identity ID

    Returns:
        Confirmation or error message
    """
    ctx = get_worker_context()

    try:
        ctx.deaddrop.add_room_member(
            ns=ctx.namespace_id,
            room_id=room_id,
            identity_id=worker_id,
            secret=ctx.identity_secret,
        )
        return f"✓ Invited {worker_id[:8]}... to room {room_id[:8]}..."
    except Exception as e:
        return f"❌ Failed to invite: {e}"


def send_to_room(
    context: "AgentContext" = None,
    room_id: str = "",
    message: str = "",
    message_type: str = "text",
) -> str:
    """Send a message to a collaboration room.

    Args:
        room_id: The room to send to
        message: The message content
        message_type: Type of message ("text", "json", or custom)

    Returns:
        Confirmation or error message
    """
    ctx = get_worker_context()
    agent_id = get_worker_agent_id()

    import json

    body = json.dumps(
        {
            "type": message_type,
            "from_agent": agent_id,
            "content": message,
        }
    )

    try:
        ctx.deaddrop.send_room_message(
            ns=ctx.namespace_id,
            room_id=room_id,
            body=body,
            secret=ctx.identity_secret,
            content_type="application/vnd.silica.worker-message+json",
        )
        return f"✓ Message sent to room {room_id[:8]}..."
    except Exception as e:
        return f"❌ Failed to send: {e}"


def list_my_rooms(context: "AgentContext" = None) -> str:
    """List rooms you're a member of.

    Returns:
        Formatted list of rooms
    """
    ctx = get_worker_context()

    try:
        rooms = ctx.deaddrop.list_rooms(
            ns=ctx.namespace_id,
            secret=ctx.identity_secret,
        )
    except Exception as e:
        return f"❌ Could not list rooms: {e}"

    if not rooms:
        return "You're not a member of any rooms (besides the main coordination room)."

    lines = [f"**{len(rooms)} room(s):**\n"]

    for room in rooms:
        room_id = room.get("room_id", "unknown")
        name = room.get("display_name", "Unnamed")
        member_count = room.get("member_count", "?")

        if room_id == ctx.room_id:
            lines.append(
                f"- **{name}** ({room_id[:8]}...) - {member_count} members [coordination]"
            )
        else:
            lines.append(f"- **{name}** ({room_id[:8]}...) - {member_count} members")

    return "\n".join(lines)


def get_room_messages(
    context: "AgentContext" = None,
    room_id: str = "",
    limit: int = 20,
) -> str:
    """Get recent messages from a room.

    Args:
        room_id: The room to read from
        limit: Maximum number of messages to return

    Returns:
        Formatted list of messages
    """
    ctx = get_worker_context()

    try:
        messages = ctx.deaddrop.get_room_messages(
            ns=ctx.namespace_id,
            room_id=room_id,
            secret=ctx.identity_secret,
        )
    except Exception as e:
        return f"❌ Could not get messages: {e}"

    if not messages:
        return "No messages in this room."

    # Limit and reverse to show oldest first
    messages = messages[-limit:]

    lines = [f"**{len(messages)} message(s) from room {room_id[:8]}...:**\n"]

    for msg in messages:
        from_id = msg.get("from_id", "unknown")[:8]
        body = msg.get("body", "")
        created = msg.get("created_at", "")[:19]  # Trim to datetime

        # Try to parse as worker message
        try:
            import json

            parsed = json.loads(body)
            if "from_agent" in parsed:
                from_id = parsed.get("from_agent", from_id)
            content = parsed.get("content", body)
        except Exception:
            content = body

        lines.append(f"[{created}] **{from_id}**: {content[:200]}")

    return "\n".join(lines)
