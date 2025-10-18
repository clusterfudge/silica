# Compaction CLI Commands - Implementation Summary

## Overview

Added two new CLI commands to give users manual control over conversation compaction:
1. **`/compact`** - Full conversation compaction
2. **`/mc [N]`** - Micro-compact first N turns (default 3)

## Motivation

While automatic compaction works well, users sometimes want manual control over when and how compaction occurs:
- **Explicit control**: Trigger compaction at strategic points (topic transitions, task completion)
- **Fine-grained compaction**: Compress only older parts while preserving recent context
- **Testing and debugging**: Manually trigger compaction to test behavior
- **Cost optimization**: Proactively reduce token usage before it becomes an issue

## Implementation

### Files Modified

1. **`silica/developer/toolbox.py`**
   - Added `_compact()` method for full compaction
   - Added `_micro_compact()` method for selective compaction
   - Registered both commands in `__init__`
   - Updated `_help()` and `_tips()` to document new commands

### Key Features

#### `/compact` Command
```python
def _compact(self, user_interface, sandbox, user_input, *args, **kwargs):
    """Explicitly trigger full conversation compaction."""
```

Features:
- Forces compaction regardless of token count
- Uses existing `ConversationCompacter` infrastructure
- Archives original conversation with timestamp
- Updates context in place
- Displays detailed statistics (compression ratio, token counts, archive name)
- Flushes the compacted state to disk

#### `/mc [N]` Command
```python
def _micro_compact(self, user_interface, sandbox, user_input, *args, **kwargs):
    """Micro-compact: summarize first N turns and keep the rest."""
```

Features:
- Compacts only the first N conversation turns (default 3)
- One turn = user message + assistant response
- Generates summary of compacted portion only
- Keeps all remaining messages intact
- No archiving (lightweight operation)
- Shows before/after statistics

### Usage Examples

#### Full Compaction
```bash
> /compact
Compacting conversation (this may take a moment)...

✓ Conversation compacted successfully!
**Original:** 240 messages (85,000 tokens)
**Compacted:** 3 messages (1,500 tokens)
**Compression ratio:** 1.8%
**Archive:** pre-compaction-20251017_143022.json
```

#### Micro-Compaction (Default)
```bash
> /mc
Micro-compacting first 3 turns (this may take a moment)...

✓ Micro-compaction completed!
**Compacted:** First 3 turns (6 messages)
**Kept:** 8 messages from the rest of the conversation
**Final message count:** 9 (was 14)
```

#### Micro-Compaction (Custom)
```bash
> /mc 5
Micro-compacting first 5 turns (this may take a moment)...

✓ Micro-compaction completed!
**Compacted:** First 5 turns (10 messages)
**Kept:** 20 messages from the rest of the conversation
**Final message count:** 21 (was 30)
```

## Technical Details

### Architecture

Both commands leverage the existing compaction infrastructure:
- Use `ConversationCompacter` class for token counting and summarization
- Respect existing model configuration
- Maintain session ID continuity
- Integrate with history persistence system

### Error Handling

Comprehensive validation:
- Check for sufficient message history
- Validate integer input for `/mc`
- Provide clear error messages
- Display full stack traces for debugging

### Testing

Created comprehensive test suite: `tests/developer/test_compaction_commands.py`

Test coverage:
- ✓ Full compaction with sufficient messages
- ✓ Full compaction with insufficient messages (error case)
- ✓ Micro-compact with default (3 turns)
- ✓ Micro-compact with custom turn count
- ✓ Micro-compact with insufficient messages (error case)
- ✓ Micro-compact with invalid input (error case)

All tests pass: **6/6 passed in 0.67s**

## Documentation

### Files Created

1. **`docs/developer/compaction_commands.md`**
   - Complete command reference
   - Usage examples and best practices
   - Comparison table between `/compact` and `/mc`
   - Technical details and error handling
   - Recommended workflows

2. **`COMPACTION_COMMANDS_SUMMARY.md`** (this file)
   - Implementation summary
   - Technical architecture
   - Testing coverage

### Files Updated

1. **`silica/developer/toolbox.py`**
   - Added commands to help text
   - Updated tips section with compaction guidance

## Comparison: `/compact` vs `/mc`

| Aspect | `/compact` | `/mc [N]` |
|--------|-----------|-----------|
| **Scope** | Entire conversation | First N turns only |
| **Archives** | Yes (timestamped) | No |
| **Recent Context** | Last 2 turns preserved | All remaining messages preserved |
| **Use Case** | Major reset/topic change | Incremental optimization |
| **Compression** | Maximum | Moderate (adjustable) |
| **API Calls** | 1 (full summary) | 1 (partial summary) |

## Benefits

### User Benefits
1. **Control**: Users decide when and how to compact
2. **Flexibility**: Choose between full and partial compaction
3. **Transparency**: See exact results and statistics
4. **Optimization**: Proactively manage token usage

### Developer Benefits
1. **Reusability**: Leverages existing compaction infrastructure
2. **Testing**: Manual trigger makes testing easier
3. **Debugging**: Users can test compaction behavior
4. **Maintenance**: Minimal new code, follows existing patterns

## Best Practices

### When to use `/compact`:
- Topic transitions or task completion
- Before major context shifts
- When maximum compression is needed
- When archiving is desired

### When to use `/mc`:
- During long iterative work sessions
- When early setup details are no longer relevant
- For progressive compaction as conversation grows
- When preserving recent context is critical

### Recommended Workflow:
```
1. Initial work (20 exchanges)
   └─> /mc 5     # Compact early setup

2. Continue work (20 more exchanges)
   └─> /mc 10    # Compact older content

3. Major topic change
   └─> /compact  # Full reset
```

## Future Enhancements

Possible improvements:
1. **Auto-suggest**: Suggest compaction when nearing threshold
2. **Preview**: Show what would be compacted before executing
3. **Undo**: Allow reverting a compaction from archive
4. **Selective**: Compact specific message ranges (e.g., `/mc 5-10`)
5. **Stats**: Show token usage before/after without compacting
6. **Templates**: Save compaction preferences per project

## Related Work

- Automatic compaction at 65% threshold (COMPACTION_FIX_SUMMARY.md)
- `SILICA_DEBUG_COMPACTION` environment variable for debugging
- `SILICA_COMPACTION_THRESHOLD` for automatic threshold control
- Session archiving and history management
- Token counting improvements (HDEV-61)

## Testing Instructions

Run the test suite:
```bash
pytest tests/developer/test_compaction_commands.py -v
```

Manual testing:
```bash
# Start silica
silica

# Have a conversation with 8+ messages
# Then try:
/mc 2        # Should compact first 2 turns
/mc 5        # Should show error (not enough history)
/compact     # Should compact entire conversation
```

## Conclusion

These commands provide users with precise control over conversation compaction, complementing the automatic compaction system. The implementation is clean, well-tested, and integrates seamlessly with existing infrastructure.

**Impact**: Users can now optimize their conversations proactively, reducing token costs and maintaining focus on relevant context.
