# Gmail Forward Tool Examples

The `gmail_forward` tool allows you to forward Gmail messages or entire threads to specified recipients.

## Function Signature

```python
gmail_forward(
    context: AgentContext,
    message_or_thread_id: str,
    to: str,
    cc: str = "",
    bcc: str = "",
    additional_message: str = "",
) -> str
```

## Parameters

- `message_or_thread_id` (required): The ID of the message or thread to forward
- `to` (required): Email address(es) of the recipient(s), comma-separated for multiple
- `cc` (optional): Email address(es) to CC, comma-separated for multiple
- `bcc` (optional): Email address(es) to BCC, comma-separated for multiple  
- `additional_message` (optional): Additional message to include at the top of the forwarded content

## Examples

### Forward a Single Message

Forward a specific message to one recipient:

```python
result = gmail_forward(
    context,
    message_or_thread_id="msg_12345",
    to="colleague@example.com"
)
```

### Forward with Additional Message

Forward a message with your own comments:

```python
result = gmail_forward(
    context,
    message_or_thread_id="msg_12345", 
    to="team@example.com",
    additional_message="Please review this request and let me know your thoughts."
)
```

### Forward to Multiple Recipients

Forward a message to multiple recipients with CC:

```python
result = gmail_forward(
    context,
    message_or_thread_id="msg_12345",
    to="alice@example.com,bob@example.com",
    cc="manager@example.com"
)
```

### Forward an Entire Thread

Forward a complete conversation thread:

```python
result = gmail_forward(
    context,
    message_or_thread_id="thread_67890",
    to="external_partner@company.com",
    additional_message="Here's the full conversation history for context."
)
```

## How It Works

1. **Message Detection**: The tool first attempts to retrieve the ID as a single message
2. **Thread Fallback**: If that fails, it treats the ID as a thread and retrieves all messages
3. **Content Assembly**: For threads, messages are sorted chronologically and combined
4. **Subject Handling**: Automatically adds "Fwd: " prefix to the subject if not already present
5. **Content Formatting**: Formats the forwarded content with proper headers and separators

## Return Value

The function returns a string indicating success, including:
- The new message ID of the forwarded email
- Whether it was a single message or thread forward
- Number of messages forwarded (for threads)

Example return:
```
Email forwarded successfully. Message ID: sent_msg_98765
Forwarded 1 message
```

Or for threads:
```
Email forwarded successfully. Message ID: sent_msg_98765  
Forwarded 3 messages from thread
```

## Error Handling

The tool handles common error scenarios:
- Invalid message/thread IDs
- Gmail API authentication issues
- Email sending failures
- Malformed email addresses

Errors are returned as descriptive strings starting with "Error:"