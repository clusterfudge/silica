# Conversation Compaction Improvements

## Overview

This document describes improvements made to the conversation compaction system to make it trigger more reliably and provide better debugging capabilities.

## Issues Fixed

### 1. Compaction Threshold Too High

**Problem**: The default compaction threshold was set at 85% of the model's context window. For Claude 3.5 Sonnet with a 200K context window, this meant compaction wouldn't trigger until ~170K tokens (~440 messages or 220 back-and-forth exchanges). This is far too high for practical use.

**Solution**: Lowered the default threshold from 85% to 65%, which triggers compaction at ~130K tokens (~340 messages or 170 exchanges). This is still conservative but much more practical.

### 2. No Configuration Option

**Problem**: Users couldn't adjust the compaction threshold without modifying the source code.

**Solution**: Added `SILICA_COMPACTION_THRESHOLD` environment variable to allow users to configure the threshold ratio (value between 0 and 1).

Example:
```bash
# Trigger compaction at 50% of context window
export SILICA_COMPACTION_THRESHOLD=0.50

# Trigger compaction at 75% of context window
export SILICA_COMPACTION_THRESHOLD=0.75
```

### 3. Poor Debugging Visibility

**Problem**: When compaction failed or didn't trigger, there was no easy way to understand why. Errors were caught and suppressed with minimal feedback.

**Solution**: Added comprehensive debug mode via `SILICA_DEBUG_COMPACTION` environment variable that shows:
- When compaction checks occur
- Why compaction was skipped (no messages, pending tools, etc.)
- Token usage statistics
- Detailed error traces when compaction fails

Example:
```bash
export SILICA_DEBUG_COMPACTION=1
```

Debug output shows:
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

### 4. History Directory Path Handling

**Problem**: The `_get_history_dir()` method assumed `history_base_dir` was always a `Path` object, but it could be passed as a string (e.g., from `tempfile.mkdtemp()`), causing a `TypeError`.

**Solution**: Added explicit type checking and conversion to ensure `history_base_dir` is always converted to a `Path` object before use.

## Usage Guidelines

### Default Behavior

With the new 65% threshold, compaction will trigger when your conversation reaches approximately:
- **130K tokens** for Claude 3.5 Sonnet (200K context)
- **85K tokens** for Claude 3 Opus (128K context)
- **100K tokens** for Claude 3.5 Haiku (200K context)

This typically corresponds to:
- ~340 messages total
- ~170 back-and-forth exchanges
- Several hours of continuous conversation

### Adjusting the Threshold

If you find compaction triggers too often or not often enough, adjust the threshold:

```bash
# More aggressive compaction (triggers at 50% = 100K tokens)
export SILICA_COMPACTION_THRESHOLD=0.50

# More conservative compaction (triggers at 80% = 160K tokens)
export SILICA_COMPACTION_THRESHOLD=0.80
```

### Debugging Compaction Issues

If compaction isn't working as expected:

1. Enable debug mode:
   ```bash
   export SILICA_DEBUG_COMPACTION=1
   ```

2. Run your agent and observe the compaction check output

3. Look for:
   - Whether checks are being skipped (pending tools, empty history, etc.)
   - Current token usage vs. threshold
   - Any error messages with stack traces

### Understanding Token Usage

The debug output shows:
- **Context window**: Total token capacity for the model
- **Token threshold**: The point at which compaction triggers (context window × threshold ratio)
- **Current tokens**: How many tokens your conversation currently uses
- **Usage**: Percentage of context window used

## Implementation Details

### Code Changes

1. **`silica/developer/compacter.py`**:
   - Lowered `DEFAULT_COMPACTION_THRESHOLD_RATIO` from 0.85 to 0.65
   - Added environment variable support for threshold configuration
   - Added `debug` parameter to `should_compact()` method
   - Enhanced debug output showing detailed token statistics

2. **`silica/developer/agent_loop.py`**:
   - Added `SILICA_DEBUG_COMPACTION` environment variable support
   - Enhanced error handling with detailed stack traces
   - Added debug logging for compaction check decisions
   - Improved error messages to stderr

3. **`silica/developer/context.py`**:
   - Fixed `_get_history_dir()` to handle both string and Path objects
   - Added explicit type conversion for `history_base_dir`

### Testing

All existing compaction tests pass with the new changes:
- `test_compaction.py`: Core compaction functionality
- `test_compaction_timing_fix.py`: Timing and trigger conditions
- `test_compaction_session_id_stability.py`: Session ID preservation
- `test_compaction_validation.py`: Message validation

New test scripts demonstrate the improvements:
- `test_compaction_debug.py`: Shows debug output and token counting
- `test_compaction_trigger.py`: Demonstrates successful compaction with configurable threshold

## Migration Notes

### Existing Behavior

If you have code that relies on the old 85% threshold, be aware that compaction will now trigger earlier (at 65%). This should generally be an improvement, but if you need the old behavior:

```bash
export SILICA_COMPACTION_THRESHOLD=0.85
```

### No Breaking Changes

All changes are backward compatible:
- Default behavior is more aggressive but still conservative
- Environment variables are optional
- All existing tests pass
- API signatures unchanged (only added optional parameters)

## Future Improvements

Possible enhancements for future versions:

1. **Dynamic Threshold Adjustment**: Automatically adjust threshold based on conversation characteristics
2. **Token Estimation Improvements**: Better fallback when API token counting fails
3. **Compaction Strategies**: Different compaction approaches (summarize all, keep recent N, keep important messages)
4. **User Notifications**: Show compaction progress and allow user control
5. **Per-Session Configuration**: Allow threshold configuration per session or per model

## References

- Issue: "compaction isn't triggering in the agent loop"
- Related tests: `test_compaction*.py`
- Environment variables: `SILICA_COMPACTION_THRESHOLD`, `SILICA_DEBUG_COMPACTION`
