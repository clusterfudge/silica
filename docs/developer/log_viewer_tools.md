# Log Viewer Tools Comparison

Quick reference for choosing the best tool to navigate request/response logs.

## Tool Comparison Matrix

| Tool | Interface | Speed | Learning Curve | Best For |
|------|-----------|-------|----------------|----------|
| **jless** | Terminal | ⚡️⚡️⚡️ | Low | Quick browsing, vim users |
| **fx** | Terminal | ⚡️⚡️ | Very Low | Interactive exploration |
| **Log Viewer** | Web | ⚡️⚡️ | None | Visual browsing, sharing |
| **jq + less** | Terminal | ⚡️⚡️⚡️ | Medium | Power users, filtering |
| **gron** | Terminal | ⚡️⚡️ | Low | Finding specific fields |

## Detailed Recommendations

### 🏆 Best for Beginners: Log Viewer (Web)

```bash
python scripts/log_viewer.py requests.jsonl
```

**Pros:**
- No installation needed (included with silica)
- Visual interface with syntax highlighting
- Point-and-click filtering
- Works great for sharing (run on server, access from browser)
- RESTful API for programmatic access

**Cons:**
- Requires Python and FastAPI (already a dependency)
- Not available over SSH without port forwarding

**Use When:**
- You want to quickly browse logs locally
- Sharing with non-technical stakeholders
- Need visual overview of request/response patterns

---

### 🏆 Best for Terminal Power Users: jless

```bash
brew install jless
jless requests.jsonl
```

**Key Bindings:**
- `j/k` - Navigate up/down
- `h/l` - Collapse/expand
- `/` - Search
- `n/N` - Next/previous match
- `:` - Command mode
- `q` - Quit

**Pros:**
- Blazing fast, even with huge files
- Vim-like navigation feels natural
- Excellent for remote work over SSH
- Handles JSON Lines format natively

**Cons:**
- Requires installation
- Learning curve for vim-unfamiliar users

**Use When:**
- Working over SSH
- Dealing with large log files (>100MB)
- You already know vim

---

### 🏆 Best for Interactive Exploration: fx

```bash
npm install -g fx

# Convert JSON Lines to array
cat requests.jsonl | jq -s '.' > requests.json
fx requests.json
```

**Features:**
- Mouse support (click to expand/collapse)
- Arrow key navigation
- Type to search/filter
- Can edit and save JSON

**Pros:**
- Very intuitive, no learning curve
- Great for one-off exploration
- Shows structure clearly

**Cons:**
- Doesn't handle JSON Lines natively
- Requires Node.js
- Can be slow with very large files

**Use When:**
- First time looking at the logs
- Need to share screen/demo
- Exploring structure interactively

---

### 🏆 Best for Complex Queries: jq + less

```bash
# View all requests with their models
jq -C 'select(.type == "request") | {model, timestamp, messages: .messages | length}' requests.jsonl | less -R

# Calculate total tokens across all responses
jq 'select(.type == "response") | .usage.input_tokens + .usage.output_tokens' requests.jsonl | \
  awk '{sum += $1} END {print "Total tokens:", sum}'

# Find errors with context
jq -C 'select(.type == "error")' requests.jsonl | less -R
```

**Pros:**
- Most powerful filtering and transformation
- Available on all Unix systems
- Scriptable for automation
- Standard tool in many environments

**Cons:**
- Steeper learning curve
- Need to know jq syntax
- More typing for simple tasks

**Use When:**
- Need complex filtering or aggregation
- Writing scripts to analyze logs
- System doesn't allow installing other tools
- Piping results to other commands

---

### 🏆 Best for Finding Specific Fields: gron

```bash
brew install gron

# Make JSON greppable
gron requests.jsonl | grep "tool_name"

# Find all tool executions
gron requests.jsonl | grep "tool_execution"

# Get all error messages
gron requests.jsonl | grep "error_message"
```

**How it works:**
Converts JSON to discrete assignments:
```
json[0].type = "request";
json[0].model = "claude-3-5-sonnet-20241022";
json[0].timestamp = "2025-01-15T10:30:45.123456";
```

**Pros:**
- Makes JSON greppable with standard tools
- Perfect for finding specific nested fields
- Can reverse transformation back to JSON
- Very fast for targeted searches

**Cons:**
- Different mental model
- Output can be verbose
- Not great for browsing

**Use When:**
- You know what field you're looking for
- Need to find all instances of a value
- Working with deeply nested structures
- Want to use grep/awk/sed on JSON

---

## Quick Start Guide

### I just want to see what's in the logs
```bash
python scripts/log_viewer.py requests.jsonl
# or
jless requests.jsonl
```

### I need to find all errors
```bash
jq -C 'select(.type == "error")' requests.jsonl | less -R
# or
gron requests.jsonl | grep '"error"'
```

### I want to calculate token usage
```bash
jq 'select(.type == "response") | .usage | .input_tokens + .output_tokens' requests.jsonl | \
  awk '{sum += $1; count++} END {print "Total:", sum, "Average:", sum/count}'
```

### I need to find a specific tool call
```bash
gron requests.jsonl | grep "read_file"
# or
jq -C 'select(.type == "tool_execution" and .tool_name == "read_file")' requests.jsonl | less -R
```

### I want to export filtered logs
```bash
jq 'select(.type == "request" and .model == "claude-3-5-sonnet-20241022")' requests.jsonl > sonnet_requests.jsonl
```

---

## Installation Quick Reference

```bash
# Web viewer (included - uses FastAPI)
# No installation needed - already in scripts/log_viewer.py
# FastAPI and uvicorn are existing dependencies

# jless (recommended terminal tool)
brew install jless                    # macOS
cargo install jless                   # Linux/other

# fx (interactive explorer)
npm install -g fx                     # Requires Node.js

# jq (query language)
brew install jq                       # macOS
sudo apt install jq                   # Debian/Ubuntu
sudo dnf install jq                   # Fedora/RHEL

# gron (make JSON greppable)
brew install gron                     # macOS
go install github.com/tomnomnom/gron@latest  # Linux/other
```

---

## Advanced Tip: Combining Tools

Each tool excels at different tasks. Combine them:

```bash
# Use jq to filter, then explore with jless
jq 'select(.type == "request")' requests.jsonl > requests_only.jsonl
jless requests_only.jsonl

# Use gron to find, then fx to explore
gron requests.jsonl | grep "high_token" | gron -u | fx

# Use jq to aggregate, then visualize
jq -s 'group_by(.type) | map({type: .[0].type, count: length})' requests.jsonl
```

---

## Performance Considerations

| File Size | Recommended Tool | Notes |
|-----------|-----------------|-------|
| < 1MB | Any | All tools work great |
| 1-10MB | jless, jq | Fast and responsive |
| 10-100MB | jless, streaming jq | Use `jq -c` for compact output |
| > 100MB | jless, split files | Consider splitting logs by date |

**Tip:** For very large files, use `split` or `head`/`tail`:
```bash
# Split into 10MB chunks
split -b 10m requests.jsonl requests_part_

# View most recent 1000 entries
tail -n 1000 requests.jsonl | jless
```

---

## See Also

- [Request/Response Logging Documentation](request_response_logging.md)
- [jq Manual](https://stedolan.github.io/jq/manual/)
- [jless GitHub](https://github.com/PaulJuliusMartinez/jless)
- [fx GitHub](https://github.com/antonmedv/fx)
- [gron GitHub](https://github.com/tomnomnom/gron)
