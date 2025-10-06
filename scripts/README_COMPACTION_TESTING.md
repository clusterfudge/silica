# Compaction Testing Tool

This directory contains tools for manually testing and debugging conversation compaction.

## Overview

The compaction testing tool (`test_compaction.py`) allows developers to:
- Load existing conversation sessions from history
- Validate conversation structure (tool use/result pairing, message alternation, etc.)
- Run compaction on conversations
- Validate the compacted result
- Save compacted sessions for inspection
- Generate detailed validation reports

## Usage

### Basic Usage

Test compaction on a session by ID:
```bash
python scripts/test_compaction.py --session-id abc-123-def-456
```

Test compaction on a specific history file:
```bash
python scripts/test_compaction.py --history-file ~/.hdev/history/abc-123/root.json
```

### Dry Run Mode

Validate a conversation without actually performing compaction (no API calls):
```bash
python scripts/test_compaction.py --session-id abc-123-def --dry-run
```

This is useful for:
- Checking if a conversation has structural issues
- Estimating token counts
- Testing the validation logic without incurring API costs

### Verbose Output

Enable detailed output including summary text and debugging information:
```bash
python scripts/test_compaction.py --session-id abc-123-def --verbose
```

### Don't Save Output

Run compaction but don't save the result:
```bash
python scripts/test_compaction.py --session-id abc-123-def --no-save
```

## What It Tests

### 1. Message Structure Validation
- Valid message roles (user/assistant)
- Proper message alternation
- Tool use and tool result pairing
- Complete tool use blocks (id, name fields present)
- No orphaned tool results or tool uses

### 2. Compaction Process
- Token counting and threshold checking
- Summary generation
- Message preservation (last 2 turns)
- Compression ratio calculation

### 3. Compacted Result Validation
- Structural integrity maintained
- Last 2 turns properly preserved
- API compatibility (proper tool use/result pairing)
- Summary message present

### 4. Session Management
- New session ID generation
- Parent session linking
- Metadata preservation

## Output

The tool provides:
- **Session Information**: ID, model, message count, metadata
- **Validation Reports**: Detailed issues with severity levels (ERROR, WARNING, INFO)
- **Compaction Summary**: Token counts, compression ratio, preserved messages
- **Saved Files**: Compacted session in `.agent-scratchpad/` directory

### Validation Levels

- **ERROR**: Issues that will cause API errors or break functionality
- **WARNING**: Issues that may cause problems but aren't critical
- **INFO**: Informational messages (e.g., in-progress tool use)

## Example Session

```bash
$ python scripts/test_compaction.py --session-id abc-123 --verbose

======================================================================
SESSION INFORMATION
======================================================================
Session ID: abc-123-def-456
Model: claude-3-5-sonnet-latest
Message Count: 38

Message Breakdown:
  User messages: 19
  Assistant messages: 19
  Tool use blocks: 18
  Tool result blocks: 18

======================================================================
VALIDATING ORIGINAL CONVERSATION
======================================================================
Validation Status: VALID
Total Messages: 38
Tool Use Blocks: 18
Tool Result Blocks: 18
Issues: 0 errors, 0 warnings, 0 info

======================================================================
Proceed with compaction? This will call the Anthropic API. (y/N): y

======================================================================
RUNNING COMPACTION
======================================================================
Should compact: True

Token Analysis:
  Current tokens: 45,234
  Context window: 200,000
  Threshold (85%): 170,000
  Utilization: 22.6%

⏳ Generating compaction summary...

✅ Compaction complete!

Compaction Summary:
  Original messages: 38
  Original tokens: 45,234
  Summary tokens: 1,523
  Compression ratio: 3.37%
  Token reduction: 96.6%

======================================================================
VALIDATING COMPACTED CONVERSATION
======================================================================
Validation Status: VALID
...

======================================================================
SAVING COMPACTED SESSION
======================================================================
✅ Saved compacted session to: .agent-scratchpad/xyz-789-new.json
   New Session ID: xyz-789-new
   Original Session ID: abc-123-def-456

======================================================================
TEST SUMMARY
======================================================================
Status: ✅ PASSED

✅ All validations passed - compacted conversation is API compatible
```

## Integration with Eval Suites

This tool is designed for manual testing but can be adapted for automated evaluation:

1. **Batch Testing**: Run on multiple sessions to collect metrics
2. **Regression Testing**: Verify compaction doesn't break conversations
3. **Performance Metrics**: Track compression ratios and token savings
4. **Quality Assurance**: Ensure API compatibility across different conversation types

## Related Files

- `silica/developer/compaction_validation.py` - Validation logic
- `silica/developer/compacter.py` - Compaction implementation
- `silica/developer/context.py` - Session management
- `tests/developer/test_compaction_validation.py` - Unit tests

## Troubleshooting

### "Session file not found"
Ensure the session ID or file path is correct. Sessions are stored in `~/.hdev/history/{session-id}/root.json`.

### "Invalid JSON in session file"
The session file may be corrupted. Check the file manually or use a different session.

### "Original conversation has validation errors"
The conversation has structural issues. The tool will prompt you to continue anyway, but the compacted result may also have issues.

### API Errors During Compaction
Ensure your `ANTHROPIC_API_KEY` is set in the environment or `.env` file. Use `--dry-run` to test without API calls.
