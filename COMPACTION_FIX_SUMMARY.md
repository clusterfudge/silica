# Compaction Fix Summary

## Problem

Conversation compaction wasn't triggering in the agent loop, causing conversations to grow very large before any summarization occurred.

## Root Causes

After investigation, I found **three main issues**:

1. **Threshold Too High**: The default compaction threshold was 85% of the context window
   - For Claude 3.5 Sonnet (200K context): triggered at ~170K tokens
   - Required ~440 messages (220 back-and-forth exchanges)
   - Far too high for practical conversations

2. **No Debugging Visibility**: When compaction didn't trigger, there was no way to see why
   - Errors were silently caught and suppressed
   - No indication of current token usage vs. threshold
   - No visibility into compaction check decisions

3. **No User Configuration**: Users couldn't adjust the threshold without modifying source code

4. **Minor Bug**: Path handling issue in `_get_history_dir()` when `history_base_dir` is a string

## Solutions Implemented

### 1. Lowered Default Threshold (65%)

Changed `DEFAULT_COMPACTION_THRESHOLD_RATIO` from `0.85` to `0.65`:
- Now triggers at ~130K tokens (65% of 200K context)
- Corresponds to ~340 messages or 170 exchanges
- Still conservative but much more practical

### 2. Added Environment Variable Configuration

New environment variable: `SILICA_COMPACTION_THRESHOLD`
```bash
# Trigger at 50% of context window (more aggressive)
export SILICA_COMPACTION_THRESHOLD=0.50

# Trigger at 80% of context window (more conservative)
export SILICA_COMPACTION_THRESHOLD=0.80
```

### 3. Added Debug Mode

New environment variable: `SILICA_DEBUG_COMPACTION`
```bash
export SILICA_DEBUG_COMPACTION=1
```

Provides detailed output:
```
[Compaction] Checking if compaction needed...

[Compaction Check]
  Model: claude-3-5-sonnet-20241022
  Context window: 200,000
  Threshold ratio: 65%
  Token threshold: 130,000
  Current tokens: 38,350
  Usage: 19.2%
  Should compact: False
[Compaction] Not needed yet
```

### 4. Improved Error Handling

- Better error messages showing full stack traces
- Errors printed to stderr for visibility
- Clear indication when compaction checks are skipped

### 5. Fixed Path Handling

Fixed `_get_history_dir()` to handle both string and Path objects for `history_base_dir`.

## Files Changed

1. **silica/developer/compacter.py**
   - Lowered default threshold from 0.85 to 0.65
   - Added `SILICA_COMPACTION_THRESHOLD` environment variable support
   - Added `debug` parameter to `should_compact()` method
   - Enhanced debug output with token statistics

2. **silica/developer/agent_loop.py**
   - Added `SILICA_DEBUG_COMPACTION` environment variable support
   - Enhanced error handling with detailed stack traces
   - Added debug logging for compaction decisions

3. **silica/developer/context.py**
   - Fixed `_get_history_dir()` to handle both string and Path objects

4. **.env.example**
   - Documented new environment variables

5. **docs/developer/compaction_improvements.md**
   - Comprehensive documentation of changes and usage

## Testing

All existing tests pass:
```bash
$ python -m pytest tests/developer/test_compaction*.py -v
======================== 23 passed in 0.42s =========================
```

Test coverage includes:
- Core compaction functionality
- Timing and trigger conditions  
- Session ID preservation
- Message validation
- New threshold behavior

## Usage Examples

### Default Behavior (Recommended)

No configuration needed. Compaction triggers at 65% (130K tokens):
```bash
# Just run your agent normally
silica
```

### More Aggressive Compaction

For shorter conversations or limited memory:
```bash
export SILICA_COMPACTION_THRESHOLD=0.50
silica
```

### More Conservative Compaction

For very long conversations where you want to delay compaction:
```bash
export SILICA_COMPACTION_THRESHOLD=0.80
silica
```

### Debugging Compaction Issues

To see what's happening with compaction:
```bash
export SILICA_DEBUG_COMPACTION=1
silica
```

## Migration Notes

### Breaking Changes
None. All changes are backward compatible.

### Behavior Changes
- Compaction now triggers earlier (65% instead of 85%)
- This is generally an improvement but can be reverted via environment variable

### Old Behavior
To restore the old 85% threshold:
```bash
export SILICA_COMPACTION_THRESHOLD=0.85
```

## Verification

To verify compaction is working:

1. Enable debug mode:
   ```bash
   export SILICA_DEBUG_COMPACTION=1
   ```

2. Have a long conversation with the agent

3. Watch for compaction check output showing token usage

4. When usage exceeds threshold, you'll see:
   ```
   [Compaction] Checking if compaction needed...
   [Compaction Check]
     ...
     Should compact: True
   Conversation compacted: 240 messages → 3 messages
   ```

## Impact

- **Users**: Compaction now triggers at reasonable conversation lengths
- **Performance**: Conversations stay within manageable token limits
- **Debugging**: Clear visibility into compaction behavior
- **Flexibility**: Easy configuration without code changes

## Related Issues

- Original issue: "compaction isn't triggering in the agent loop"
- Related documentation: `docs/developer/compaction_improvements.md`
- Related tests: `tests/developer/test_compaction*.py`
