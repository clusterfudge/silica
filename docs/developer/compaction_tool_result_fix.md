# Compaction Tool Result Bug Fix

## Problem

After conversation compaction, users encountered this error:

```
Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 
'message': 'messages.0.content.1: unexpected `tool_use_id` found in `tool_result` blocks: 
toolu_01Aag7r6oXy5koKb4M69RUno. Each `tool_result` block must have a corresponding `tool_use` 
block in the previous message.'}}
```

## Root Cause

The `compact_conversation` method in `silica/developer/compacter.py` was preserving the last 2 messages from the conversation history after creating a summary. This created invalid message sequences when:

1. The second-to-last message was an assistant message with `tool_use` blocks
2. The last message was a user message with `tool_result` blocks
3. A summary user message was prepended to these preserved messages

While the tool_use/tool_result pairing itself was technically valid, the presence of an additional user message (the summary) before the tool_use created ambiguity in message sequencing that could trigger API validation errors.

### Original Code

```python
# Create a new conversation with the summary
new_messages = [
    {
        "role": "user",
        "content": (
            f"### Conversation Summary (Compacted from {summary.original_message_count} previous messages)\n\n"
            f"{summary.summary}\n\n"
            f"Continue the conversation from this point."
        ),
    }
]

# Preserve the last 2 messages for context
context_dict = agent_context.get_api_context()
messages_to_use = context_dict["messages"]
if len(messages_to_use) >= 2:
    new_messages.extend(messages_to_use[-2:])  # <-- Problem here
```

This could create:
```python
[
    {"role": "user", "content": "Summary..."},          # New message
    {"role": "assistant", "content": [tool_use]},       # Preserved
    {"role": "user", "content": [tool_result]},         # Preserved
]
```

## Solution

The fix removes the preservation of old messages entirely. The summary provides sufficient context to continue the conversation, and not preserving partial message exchanges eliminates the possibility of creating invalid tool_use/tool_result sequences.

### Fixed Code

```python
# Create a new conversation with the summary
# Note: We use a list for content to maintain consistency with other messages
new_messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": (
                    f"### Conversation Summary (Compacted from {summary.original_message_count} previous messages)\n\n"
                    f"{summary.summary}\n\n"
                    f"Continue the conversation from this point."
                ),
            }
        ],
    }
]

# Don't preserve old messages - they can create invalid tool_use/tool_result sequences
return new_messages, summary
```

Now compaction always creates:
```python
[
    {"role": "user", "content": [{"type": "text", "text": "Summary..."}]},
]
```

## Benefits

1. **Eliminates the bug**: No risk of orphaned tool_result references
2. **Simpler code**: No complex logic to validate message pairing
3. **Consistent format**: Summary message uses the same list-based content format as other user messages
4. **Cleaner state**: New conversation starts completely fresh with just the summary

## Trade-offs

- **Less immediate context**: Previous approach kept the last exchange visible, which could help with very recent references
- **Reliance on summary quality**: The summary must be comprehensive enough to maintain continuity

In practice, the Claude model's summarization is sufficiently detailed that this trade-off is acceptable, and the elimination of API errors far outweighs any minor loss of immediate context.

## Testing

New tests in `tests/developer/test_compaction_tool_result_bug.py` verify:

1. Compacted messages contain only the summary (no preserved messages)
2. Summary message content is a list (not a string)
3. No orphaned tool_result blocks exist in compacted conversations

All existing compaction tests continue to pass.

## Related Files

- `silica/developer/compacter.py` - Main fix
- `silica/developer/agent_loop.py` - Compaction invocation (unchanged)
- `tests/developer/test_compaction_tool_result_bug.py` - New tests
- `tests/developer/test_compaction.py` - Existing tests (still passing)
- `tests/developer/test_compaction_timing_fix.py` - Existing tests (still passing)
