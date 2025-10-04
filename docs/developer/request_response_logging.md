# Request/Response Logging

The developer agent supports comprehensive logging of all API requests and responses to JSON log files. This is useful for debugging, analysis, cost tracking, and understanding agent behavior.

## Usage

Enable logging by using the `--log-requests` flag with a path to the log file:

```bash
silica --log-requests requests.jsonl
```

Or with a full path:

```bash
silica --log-requests /path/to/logs/requests.jsonl
```

## Log Format

Logs are written in JSON Lines format (one JSON object per line), making them easy to parse and analyze with tools like `jq`, Python, or other JSON processors.

### Log Entry Types

#### 1. Request Entries

Logged before each API call to the LLM:

```json
{
  "type": "request",
  "timestamp": "2025-01-15T10:30:45.123456",
  "unix_timestamp": 1705318245.123,
  "model": "claude-3-5-sonnet-20241022",
  "max_tokens": 4096,
  "system": [...],
  "messages": [...],
  "tools": [...],
  "thinking": null
}
```

#### 2. Response Entries

Logged after each API response:

```json
{
  "type": "response",
  "timestamp": "2025-01-15T10:30:47.456789",
  "unix_timestamp": 1705318247.456,
  "message_id": "msg_abc123",
  "stop_reason": "end_turn",
  "content": [...],
  "usage": {
    "input_tokens": 1234,
    "output_tokens": 567,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 890
  },
  "thinking_content": null
}
```

#### 3. Tool Execution Entries

Logged for each tool invocation:

```json
{
  "type": "tool_execution",
  "timestamp": "2025-01-15T10:30:48.789012",
  "unix_timestamp": 1705318248.789,
  "tool_name": "read_file",
  "input": {
    "path": "example.py"
  },
  "result": {
    "type": "tool_result",
    "tool_use_id": "toolu_xyz789",
    "content": "..."
  }
}
```

**Note:** Tool result content is automatically truncated to 10KB to prevent massive log files. If truncated, a message will be appended indicating how many characters were removed.

#### 4. Error Entries

Logged when errors occur (rate limits, API errors, etc.):

```json
{
  "type": "error",
  "timestamp": "2025-01-15T10:30:49.012345",
  "unix_timestamp": 1705318249.012,
  "error_type": "RateLimitError",
  "error_message": "Rate limit exceeded",
  "context": {
    "attempt": 1,
    "max_retries": 5,
    "backoff_time": 2.5
  }
}
```

## Analyzing Logs

### Quick Recommendation: Best Tools

**For terminal users:**
- **jless** - Modern, fast JSON viewer with vim-style navigation (recommended)
- **fx** - Interactive JSON explorer with mouse support
- **jq + less** - Classic Unix approach with powerful filtering

**For web interface:**
- **Built-in log viewer** - Run `python scripts/log_viewer.py requests.jsonl` (included with silica)

### Built-in Web Viewer

Silica includes a simple web-based log viewer:

```bash
python scripts/log_viewer.py requests.jsonl
# Open http://localhost:8000
```

**Features:**
- Browse logs in sidebar with syntax highlighting
- Filter by type (request, response, tool_execution, error)
- Search across all fields
- Keyboard navigation (arrow keys)
- Statistics dashboard
- Dark theme optimized for reading JSON

### Terminal Tools

#### jless (Recommended)
```bash
# Install
brew install jless  # macOS
cargo install jless  # Linux/other

# Use
jless requests.jsonl

# Navigation
# j/k - up/down
# / - search
# Space - toggle expand/collapse
# q - quit
```

#### fx (Interactive)
```bash
# Install
npm install -g fx

# Convert JSON Lines to array first
cat requests.jsonl | jq -s '.' > requests.json
fx requests.json

# Or use with streaming
cat requests.jsonl | fx
```

#### jq + less (Classic)
```bash
# Pretty-print and page
jq -C '.' requests.jsonl | less -R

# Filter and navigate
jq -C 'select(.type == "request")' requests.jsonl | less -R
```

### Using jq

Count total requests:
```bash
jq 'select(.type == "request")' requests.jsonl | wc -l
```

Calculate total token usage:
```bash
jq 'select(.type == "response") | .usage.input_tokens + .usage.output_tokens' requests.jsonl | \
  awk '{sum += $1} END {print sum}'
```

Extract all tool executions:
```bash
jq 'select(.type == "tool_execution") | {tool: .tool_name, input: .input}' requests.jsonl
```

Find rate limit errors:
```bash
jq 'select(.type == "error" and .error_type == "RateLimitError")' requests.jsonl
```

### Using Python

```python
import json

# Read and parse log file
with open('requests.jsonl') as f:
    logs = [json.loads(line) for line in f]

# Count requests by type
from collections import Counter
type_counts = Counter(log['type'] for log in logs)
print(type_counts)

# Calculate total cost (if pricing info is available)
responses = [log for log in logs if log['type'] == 'response']
total_input_tokens = sum(r['usage']['input_tokens'] for r in responses)
total_output_tokens = sum(r['usage']['output_tokens'] for r in responses)
print(f"Input: {total_input_tokens}, Output: {total_output_tokens}")

# Find most used tools
tool_logs = [log for log in logs if log['type'] == 'tool_execution']
tool_counts = Counter(log['tool_name'] for log in tool_logs)
print(tool_counts.most_common(5))
```

## Privacy and Security Considerations

**⚠️ Important:** Log files contain the full content of your conversations, including:
- User prompts and messages
- System prompts and agent instructions
- File contents (via tool results)
- API responses

**Best practices:**
- Store log files in secure locations with appropriate permissions
- Exclude log files from version control (add `*.jsonl` to `.gitignore`)
- Rotate and archive logs regularly
- Sanitize logs before sharing or uploading
- Consider encrypting log files containing sensitive information

## Performance Impact

Logging has minimal performance impact:
- Log writes are non-blocking and happen after API responses
- Failed log writes don't disrupt agent operation
- Log entries are written immediately (no buffering)

However, very large conversations with many tool calls can generate substantial log file sizes. The automatic truncation of tool results helps manage this.

## Disabling Logging

Logging is **disabled by default**. Simply omit the `--log-requests` flag to run without logging.

## Troubleshooting

### Log file not created

The logger creates parent directories automatically, but check that:
- The parent directory is writable
- You have sufficient disk space
- The path is valid

### Missing log entries

Verify that:
- Logging was enabled with `--log-requests`
- The path is correct
- No other process has exclusive access to the file

### Large log files

- Tool results are automatically truncated to 10KB per entry
- Consider rotating logs by date or conversation
- Compress old logs with `gzip` or similar tools

## Examples

### Basic usage
```bash
silica --log-requests agent.log --prompt "Analyze this code"
```

### With custom persona and logging
```bash
silica --persona code_reviewer --log-requests reviews.jsonl
```

### DWR mode with logging
```bash
silica --dwr --log-requests autonomous_session.jsonl
```

### Resume session with logging
```bash
silica --session-id abc123 --log-requests continued_session.jsonl
```

## Integration with Other Tools

The JSON Lines format makes it easy to integrate with:
- **Elasticsearch/Logstash**: For search and visualization
- **Jupyter Notebooks**: For interactive analysis
- **Pandas**: For data analysis and statistics
- **Custom dashboards**: Parse and visualize usage patterns
- **Cost tracking tools**: Extract token usage for billing analysis
