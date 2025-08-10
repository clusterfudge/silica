# Session Management in Heare Developer

Heare Developer now includes CLI tools for managing and resuming previous development sessions. This is built on top of the session metadata introduced in HDEV-58.

## Features

- List previous sessions with metadata
- Filter sessions by working directory
- Resume a previous session from its ID
- Improved state management within AgentContext

## Using the Session Management Tools

### Listing Available Sessions

To list all available sessions with metadata:

```bash
hdev sessions
```

This will display a table with the following information:
- Session ID
- Creation date
- Last updated date
- Number of messages
- Model used
- Root directory

You can filter sessions by a specific working directory:

```bash
hdev sessions /path/to/project
```

This will only show sessions that were created in the specified directory.

### Resuming a Previous Session

To resume a specific session:

```bash
hdev resume <session-id>
```

Where `<session-id>` is the ID of the session to resume. You can use a partial ID (just the first few characters) as long as it uniquely identifies a session.

The resume command will:
1. Find the session with the specified ID
2. Change to the original working directory where the session was created
3. Start a new Heare Developer instance with the previous session loaded

## Technical Details

### Session Metadata

Sessions include the following metadata:
- `created_at`: ISO 8601 timestamp of when the session was created
- `last_updated`: ISO 8601 timestamp of when the session was last updated
- `root_dir`: The root directory where the session was created (typically the git repository root)

### Session Storage

Sessions are stored in the `~/.hdev/history` directory, with each session having its own subdirectory named by its UUID. The main conversation data is stored in `root.json` within that subdirectory.

### Integration with Heare Developer

When resuming a session, the CLI loads the previous conversation history and continues from where you left off. This allows you to maintain context across multiple development sessions.

### AgentContext Encapsulation

The session state (chat history and tool results) is now fully encapsulated within the AgentContext class. This design improvement provides several benefits:

1. **State Consistency**: All session state is stored in one place, making it easier to manage.
2. **Cleaner Resumption**: When resuming a session, the entire context is loaded at once with its state.
3. **Improved Agent Loop**: The agent run loop no longer needs to manage and track state separately.

The key properties of AgentContext for session management are:
- `chat_history`: Contains all messages in the conversation
- `tool_result_buffer`: Stores pending tool results to be processed

This encapsulation ensures state is managed consistently across all operations, including during session resumption and agent sub-context creation.

## Requirements

This feature relies on the metadata implementation from HDEV-58. Sessions without proper metadata (created before HDEV-58) will not be listed or available for resumption.