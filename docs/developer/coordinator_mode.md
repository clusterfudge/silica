# Coordinator Mode

Coordinator mode enables multi-agent orchestration where a coordinator agent spawns and manages worker agents asynchronously via deaddrop messaging.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    Coordinator Agent                          │
│  (Limited tools: memory, web, coordination)                   │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ spawn_agent │  │ message_    │  │ poll_       │          │
│  │             │  │ agent       │  │ messages    │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         │ deaddrop
                         │ (namespace + room)
                         │
    ┌────────────────────┼────────────────────┐
    │                    │                    │
    ▼                    ▼                    ▼
┌──────────┐      ┌──────────┐      ┌──────────┐
│ Worker 1 │      │ Worker 2 │      │ Worker 3 │
│ (Opus)   │      │ (Opus)   │      │ (Opus)   │
│          │      │          │      │          │
│ Full     │      │ Full     │      │ Full     │
│ tools    │      │ tools    │      │ tools    │
└──────────┘      └──────────┘      └──────────┘
```

## CLI Usage

### Starting a Coordinator Session

```bash
# Create a new coordination session
silica coordinator new --name "Feature Development"

# List existing sessions
silica coordinator list

# Resume an existing session
silica coordinator resume abc12345

# View session details
silica coordinator info abc12345

# Delete a session
silica coordinator delete abc12345 -f
```

### Remote Coordination

Start a coordinator in a remote workspace:

```bash
# Using the --coordinator flag
silica remote tell -w agent -c "build a web scraper with parallel workers"

# Using the coordinate: prefix
silica remote tell -w agent "coordinate: review all PRs and summarize issues"
```

## Coordinator Tools

### Agent Management

| Tool | Description |
|------|-------------|
| `spawn_agent(workspace_name, display_name, remote)` | Create a new worker agent |
| `list_agents(filter_state, details)` | List registered agents |
| `terminate_agent(agent_id, reason)` | Terminate a worker |
| `check_agent_health(threshold_minutes)` | Find stale agents |

### Messaging

| Tool | Description |
|------|-------------|
| `message_agent(agent_id, message_type, **kwargs)` | Send to agent inbox |
| `broadcast(message_type, **kwargs)` | Send to coordination room |
| `poll_messages(wait, include_room)` | Receive messages |

### Session Management

| Tool | Description |
|------|-------------|
| `get_session_state()` | View session info and statistics |
| `create_human_invite(name, expires_in)` | Create invite for human observer |

### Permission Handling

| Tool | Description |
|------|-------------|
| `grant_permission(request_id, decision, agent_id, reason)` | Grant/deny a request |
| `list_pending_permissions(agent_id, status)` | View queued permissions |
| `grant_queued_permission(request_id, decision, reason)` | Process queued request |
| `escalate_to_user(request_id, context)` | Send to human |
| `clear_expired_permissions(max_age_hours)` | Clean up old requests |

## Worker Tools

Workers have full tool access plus coordination tools:

| Tool | Description |
|------|-------------|
| `check_inbox(wait)` | Poll for messages from coordinator |
| `send_to_coordinator(message_type, **kwargs)` | Send to coordinator |
| `broadcast_status(message)` | Broadcast to room |
| `mark_idle(completed_task_id)` | Signal availability |
| `request_permission(action, resource, context, timeout)` | Request permission |
| `request_permission_async(action, resource, context)` | Non-blocking request |

## Message Protocol

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| `TaskAssign` | Coordinator → Worker | Assign work |
| `TaskAck` | Worker → Coordinator | Acknowledge task |
| `Progress` | Worker → Room | Status update |
| `Result` | Worker → Coordinator | Task completion |
| `PermissionRequest` | Worker → Coordinator | Request permission |
| `PermissionResponse` | Coordinator → Worker | Grant/deny |
| `Idle` | Worker → Room | Available for work |
| `Question` | Worker → Coordinator | Ask clarification |
| `Answer` | Coordinator → Worker | Respond |
| `Terminate` | Coordinator → Worker | Shutdown |

### Example: TaskAssign

```python
{
    "type": "task_assign",
    "task_id": "task-abc123",
    "description": "Implement the user authentication module",
    "context": "We're building a web app...",
    "files_to_modify": ["src/auth.py", "tests/test_auth.py"],
    "priority": 1,
    "timeout_minutes": 60
}
```

### Example: Result

```python
{
    "type": "result",
    "task_id": "task-abc123",
    "status": "success",  # or "failed", "timeout", "terminated"
    "summary": "Implemented auth module with tests",
    "details": "Created login, logout, and session management...",
    "artifacts": ["src/auth.py", "tests/test_auth.py"],
    "metrics": {"tests_added": 5, "lines_changed": 150}
}
```

## Permission Flow

1. Worker attempts sandboxed operation requiring permission
2. Worker sends `PermissionRequest` to coordinator
3. Coordinator reviews request (or it's queued if timeout)
4. Coordinator sends `PermissionResponse`
5. Worker proceeds or handles denial

```
Worker                    Coordinator
   │                           │
   │ ── PermissionRequest ──▶  │
   │    (action, resource)     │
   │                           │ reviews request
   │  ◀── PermissionResponse ──│
   │       (allow/deny)        │
   │                           │
```

## Session Persistence

Sessions are stored in `~/.silica/coordination/{session_id}.json`:

```json
{
    "session_id": "abc12345",
    "session_name": "Feature Development",
    "namespace_id": "ns-xxx",
    "namespace_secret": "secret-xxx",
    "coordinator_id": "coord-xxx",
    "coordinator_secret": "secret-xxx",
    "room_id": "room-xxx",
    "agents": {
        "agent-1": {
            "agent_id": "agent-1",
            "identity_id": "id-xxx",
            "display_name": "Worker 1",
            "workspace_name": "worker-1",
            "state": "idle",
            "last_seen": "2024-01-01T00:00:00Z"
        }
    },
    "humans": {},
    "pending_permissions": {},
    "created_at": "2024-01-01T00:00:00Z"
}
```

## Session Resumption

When resuming a session, the coordinator syncs agent states from room history:

```python
# Automatic sync on resume
session = CoordinationSession.resume_session(deaddrop, session_id="abc12345")

# Manual sync
session.sync_agent_states()
```

State detection from messages:
- `Idle` → agent state = IDLE
- `Progress`, `TaskAck` → agent state = WORKING
- `Result(status="terminated")` → agent state = TERMINATED
- `PermissionRequest` → queued for review

## Error Recovery

The coordination module includes graceful error handling:

- **Connection failures**: Automatic retry with exponential backoff (default 3 attempts)
- **Parse errors**: Log warning, skip message, continue processing
- **Invalid messages**: Silently skipped
- **Timeout on permission**: Returns `False` (deny by default)

```python
# Retry is enabled by default
context.send_message(to_id, message, retry=True)

# Disable retry for immediate failure
context.send_message(to_id, message, retry=False)
```

## Example Workflow

```python
# Coordinator starts session and spawns workers
session = CoordinationSession.create_session(deaddrop, "Code Review")

# Spawn workers
spawn_agent(workspace_name="reviewer-1", display_name="PR Reviewer 1")
spawn_agent(workspace_name="reviewer-2", display_name="PR Reviewer 2")

# Assign tasks
message_agent("agent-1", "task", 
    task_id="review-pr-123",
    description="Review PR #123 for security issues")
    
message_agent("agent-2", "task",
    task_id="review-pr-124", 
    description="Review PR #124 for performance")

# Poll for results
while True:
    messages = poll_messages(wait=30)
    for msg in messages:
        if msg.type == "result":
            print(f"Task {msg.task_id} completed: {msg.status}")
        elif msg.type == "permission_request":
            # Review and grant
            grant_permission(msg.request_id, "allow", msg.agent_id)
```

## Compression

Large messages are automatically compressed using gzip+base64 when beneficial:

```python
# Compression is transparent
context.send_message(to_id, large_message)  # Auto-compresses if >10KB

# Content-Type indicates compression
"application/vnd.silica.coordination+json; compression=gzip"
```

## Best Practices

1. **Break tasks down**: Assign focused, independent tasks to workers
2. **Monitor health**: Use `check_agent_health()` to detect stale workers
3. **Handle permissions promptly**: Workers block waiting for responses
4. **Use progress updates**: Workers should report progress regularly
5. **Clean up workers**: Terminate idle workers when done
6. **Persist state**: Session state auto-saves after each change
