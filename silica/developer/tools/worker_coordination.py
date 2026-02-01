"""Worker coordination tools for communicating with the coordinator.

These tools are available to worker agents spawned by a coordinator.
Workers use these to receive tasks, report progress, and request permissions.
"""

from typing import Optional
import time
import uuid

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
            "Not running as a coordinated worker. " "Worker context not initialized."
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


def check_inbox(
    wait: int = 0,
) -> str:
    """Check for new messages from the coordinator.

    Args:
        wait: Timeout in seconds to wait for messages (0 for immediate)

    Returns:
        Formatted list of messages or "No new messages"
    """
    ctx = get_worker_context()
    messages = ctx.receive_messages(wait=wait, include_room=False)

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
    message_type: str,
    **kwargs,
) -> str:
    """Send a message to the coordinator.

    Args:
        message_type: Type of message ("ack", "progress", "result", "question")
        **kwargs: Message-specific parameters

    Returns:
        Confirmation message

    For ack messages:
        - task_id: ID of task being acknowledged

    For progress messages:
        - task_id: ID of task
        - progress: Optional float 0.0-1.0
        - message: Status message

    For result messages:
        - task_id: ID of completed task
        - status: "complete", "failed", "blocked", "partial"
        - summary: Brief summary
        - data: Optional dict with results
        - error: Optional error message (for failed status)

    For question messages:
        - task_id: ID of related task
        - question: The question text
        - options: Optional list of predefined options
    """
    ctx = get_worker_context()
    agent_id = get_worker_agent_id()

    if message_type == "ack":
        task_id = kwargs.get("task_id", get_current_task() or "")
        msg = TaskAck(task_id=task_id, agent_id=agent_id)
        set_current_task(task_id)

    elif message_type == "progress":
        msg = Progress(
            task_id=kwargs.get("task_id", get_current_task() or ""),
            agent_id=agent_id,
            progress=kwargs.get("progress"),
            message=kwargs.get("message", ""),
        )

    elif message_type == "result":
        task_id = kwargs.get("task_id", get_current_task() or "")
        msg = Result(
            task_id=task_id,
            agent_id=agent_id,
            status=kwargs.get("status", "complete"),
            summary=kwargs.get("summary", ""),
            data=kwargs.get("data", {}),
            error=kwargs.get("error"),
        )
        # Clear current task after sending result
        if task_id == get_current_task():
            set_current_task(None)

    elif message_type == "question":
        question_id = kwargs.get("question_id", f"q-{uuid.uuid4().hex[:8]}")
        msg = Question(
            question_id=question_id,
            task_id=kwargs.get("task_id", get_current_task() or ""),
            agent_id=agent_id,
            question=kwargs.get("question", ""),
            options=kwargs.get("options", []),
        )

    else:
        return f"❌ Unknown message type: {message_type}"

    ctx.send_to_coordinator(msg)
    return f"✓ Sent {message_type} to coordinator"


def broadcast_status(
    message: str,
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


def mark_idle() -> str:
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
    action: str,
    resource: str,
    context: str = "",
    timeout: int = 300,
) -> str:
    """Request permission from the coordinator for a sensitive operation.

    This will block waiting for the coordinator's response.

    Args:
        action: Type of action (e.g., "shell_execute", "write_file")
        resource: The resource being accessed (e.g., command, file path)
        context: Human-readable explanation of why this is needed
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
        context=context,
    )

    ctx.send_to_coordinator(request)

    # Wait for response
    start_time = time.time()
    poll_interval = 2  # seconds

    while (time.time() - start_time) < timeout:
        messages = ctx.receive_messages(
            wait=min(poll_interval, timeout - int(time.time() - start_time)),
            include_room=False,
        )

        for recv in messages:
            msg = recv.message
            if isinstance(msg, PermissionResponse) and msg.request_id == request_id:
                return msg.decision

    return "timeout"


def request_permission_async(
    action: str,
    resource: str,
    context: str = "",
) -> str:
    """Request permission without blocking.

    Use this when you want to continue with other work while
    waiting for permission. Check inbox later for the response.

    Args:
        action: Type of action
        resource: Resource being accessed
        context: Explanation

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
        context=context,
    )

    ctx.send_to_coordinator(request)

    return f"✓ Permission request sent (ID: {request_id}). Check inbox for response."
