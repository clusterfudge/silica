# Interactive Bash Command Timeout Enhancement

## Overview

The bash command execution functionality has been enhanced with interactive timeout handling. Instead of simply failing when commands exceed the timeout period, users are now prompted with options to continue waiting, kill the process, or background it.

## Features

### Interactive Timeout Prompts
- **Default timeout**: 30 seconds
- **User choices when timeout is reached**:
  - **Continue (C)**: Wait for another timeout period
  - **Kill (K)**: Terminate the process and return results
  - **Background (B)**: Let process continue but return current output

### Real-time Output Display
- Current command output is shown during timeout prompts
- Users can see command progress to make informed decisions
- Output is captured continuously during execution

### Flexible Timeout Intervals
- Continue option extends timeout by the same initial interval
- Users can continue waiting multiple times
- Timeout periods are contextually displayed in prompts

## Usage

### Agent Tool
```python
# Will prompt after 30 seconds if still running
result = await run_bash_command(context, "long_running_command.sh")
```

### CLI Tool
```bash
# Interactive timeout handling in CLI
hdev exec "sleep 60"
```

## Example Interaction

```
Command has been running for 30.0 seconds.
Current STDOUT:
Processing file 15/100...
Analyzing data...

Command is still running. Choose action:
  [C]ontinue waiting (30s more)
  [K]ill the process
  [B]ackground (continue but return current output)
Choice (C/K/B): C

Continuing to wait for 30 more seconds...
```

## Technical Details

### Dual Implementation
- **Async version**: Used by agent tools for responsive UI
- **Sync version**: Used by CLI tools for compatibility
- Both versions provide identical functionality

### Process Management
- Non-blocking process execution with thread-based output capture
- Graceful process termination with fallback to force-kill
- Proper cleanup of threads and resources

### Security
- All existing security restrictions maintained
- Dangerous commands still blocked before execution
- Permission system integration preserved

## Backward Compatibility

- Existing functionality unchanged
- Quick-completing commands work exactly as before
- Only long-running commands see the new interactive behavior

## Testing

Comprehensive test suite covers:
- Quick command completion
- Timeout scenarios (kill, continue, background)
- Output capture during timeouts
- Error handling and edge cases
- Security restrictions
- System message verification

## Configuration

Currently uses a 30-second default timeout. This can be adjusted in the implementation if needed for specific use cases.
## Live Output Streaming

### Real-time Command Output

The enhancement includes live output streaming capabilities that provide real-time visibility into command execution:

#### Basic Live Streaming
```python
from heare.developer.tools.repl import run_bash_command_with_live_streaming

# Command output streams live to the terminal
result = await run_bash_command_with_live_streaming(context, "./build_script.sh")
```

#### Advanced Live Display Management
```python
from heare.developer.tools.repl import create_bash_live_display

# Create custom live display context
with create_bash_live_display() as live_ctx:
    result = await live_ctx.run_command(context, "long_running_process")
```

#### User Interface Integration

The live streaming works through the enhanced UserInterface system:

```python
# All UI methods now support optional live parameter
context.user_interface.handle_system_message("Status update", live=live_instance)
context.user_interface.handle_tool_result("tool_name", result, live=live_instance)
context.user_interface.bare("Direct output", live=live_instance)
```

### Live Streaming Features

- **Real-time Output**: See command output as it's generated
- **Timeout Integration**: Live display updates during timeout prompts
- **Process Completion**: Immediate display updates when processes complete
- **Backward Compatible**: All existing code continues working unchanged
- **Optional Enhancement**: Tools can opt-in to live streaming

## Benefits

- **Better UX**: No more failed commands due to arbitrary timeouts
- **User control**: Users decide when to terminate long-running commands
- **Real-time Visibility**: Live output shows command progress as it happens
- **Flexibility**: Background option for truly long-running processes
- **Safety**: Maintains all existing security and permission checks
- **Race Condition Free**: Process completion detected even during user input