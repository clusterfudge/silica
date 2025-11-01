# Compaction with Extended Thinking Mode - State Management Fix

## Problem

When a conversation is compacted while extended thinking mode is enabled, the system would crash on the next API call with a validation error:

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'messages.1.content.0.type: Expected `thinking` or `redacted_thinking`, but found `text`. When `thinking` is enabled, a final `assistant` message must start with a thinking block (preceeding the lastmost set of `tool_use` and `tool_result` blocks). We recommend you include thinking blocks from previous turns. To avoid this requirement, disable `thinking`.'}}
```

### Root Cause

The compaction process correctly:
1. Strips all thinking blocks from messages (required due to API validation complexity)
2. Ensures the conversation ends with a user message (when thinking is enabled)

**However**, it did not disable thinking mode in the agent context state. This created a mismatch:
- The messages no longer contained thinking blocks
- But `agent_context.thinking_mode` was still set to `"normal"` or `"ultra"`
- The next API call would include the `thinking` parameter
- The API would validate that the last assistant message should start with a thinking block
- But no thinking blocks exist in the messages → validation error

### Why Thinking Blocks Are Stripped During Compaction

The Anthropic API has complex validation rules for thinking blocks:

1. If ANY message has a thinking block, the `thinking` parameter must be enabled
2. If `thinking` is enabled, the LAST assistant message MUST start with a thinking block
3. Thinking blocks must precede other content types in specific orders

During compaction:
- We preserve a summary message and optionally recent messages
- We cannot guarantee the preserved messages have the correct thinking block structure
- Even if we tried to preserve thinking blocks, the structure might violate API rules
- Therefore, we strip ALL thinking blocks for safety

### Solution

After stripping thinking blocks, we now also disable thinking mode:

```python
# Strip all thinking blocks from compacted messages to avoid API validation errors
new_messages = self._strip_all_thinking_blocks(new_messages)

# Disable thinking mode after stripping thinking blocks
# The compacted conversation no longer has thinking context, and keeping thinking
# mode enabled would cause API validation errors on the next request
if agent_context.thinking_mode != "off":
    agent_context.thinking_mode = "off"
```

This ensures the agent state matches the actual message structure.

## User Impact

After compaction occurs in a conversation with thinking mode enabled:
- **Thinking mode will be automatically disabled**
- The conversation continues normally without thinking
- Users can re-enable thinking mode if desired using the `/think` command

This is preferable to crashing with a validation error.

## Implementation Details

### Location
`silica/developer/compacter.py` in the `compact_conversation()` method

### Changes
Added state management to disable thinking mode after stripping thinking blocks from messages.

### Tests
New test file: `tests/developer/test_compaction_thinking_mode_state.py`

Tests verify:
1. Thinking mode is disabled after compaction when it was set to "normal"
2. Thinking mode is disabled after compaction when it was set to "ultra"  
3. Thinking mode remains off if it was already off
4. The resulting message structure prevents API validation errors

All existing compaction tests continue to pass.

## Alternative Approaches Considered

### Option 2: Preserve thinking structure
We could try to maintain thinking blocks in preserved messages and keep thinking mode enabled.

**Rejected because:**
- API validation rules are complex and error-prone
- We'd need to ensure the final assistant message has a thinking block
- We might preserve messages that violate other structural rules
- Would require synthesizing thinking blocks, which could confuse the model

### Option 3: Don't preserve any messages when thinking is enabled
Only keep the summary message (which is from the user).

**Rejected because:**
- Loses valuable recent context
- The current approach (preserving messages but stripping thinking) works well
- Users care more about recent conversation content than thinking blocks

## Related Work

- `test_compaction_thinking_blocks.py` - Tests for stripping thinking blocks during compaction
- `test_compaction_thinking_user_message.py` - Tests for ensuring conversation ends with user message
- `docs/developer/compaction_thinking_blocks.md` - Previous thinking block handling documentation

## Future Considerations

If the Anthropic API adds support for resuming thinking mode after compaction (e.g., allowing conversations without thinking blocks to start using thinking), we could revisit this decision and allow thinking mode to remain enabled.

For now, the safest approach is to disable thinking mode when we strip the thinking context during compaction.
