# Project-Local Tools

Silica supports two locations for custom user tools:

1. **Personal tools**: `~/.silica/tools/` - Your global tools available everywhere
2. **Project tools**: `<project>/.silica/tools/` - Tools specific to a project

## Tool Precedence

When tool names conflict, personal tools take precedence over project tools. This allows you to override project tools with your own customizations.

## Tool Authorization

Some tools require authorization before they can be used (e.g., tools that access APIs).

### How it works:
1. Tools declare `requires_auth: true` in their metadata
2. Tools implement `--authorize` flag that checks/performs authorization
3. Unauthorized tools are excluded from the agent's tool schema

### Authorizing tools:
```bash
# List tools that need authorization
/auth-tool

# Authorize a specific tool
/auth-tool github
```

### Creating tools that require auth:

In your tool's metadata:
```python
"""My API Tool.

Metadata:
    requires_auth: true
"""
```

Implement `--authorize`:
```python
if "--authorize" in sys.argv:
    # Check if authorized
    if is_authorized():
        print(json.dumps({"success": True, "message": "Authorized"}))
    else:
        print(json.dumps({"success": False, "message": "Not authorized"}))
        # Optionally start interactive auth flow
        sys.exit(1)
```

## Creating Project Tools

Project tools work exactly like personal tools but are stored in the project's `.silica/tools/` directory:

```bash
# Create the project tools directory
mkdir -p .silica/tools

# Create a tool (same format as personal tools)
cat > .silica/tools/my_tool.py << 'EOF'
#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts"]
# ///
...
EOF

chmod +x .silica/tools/my_tool.py
```

## Version Control

By default, the `.silica/` directory is gitignored. If you want to version control project-local tools, update your `.gitignore`:

```gitignore
# Instead of:
# .silica/

# Use:
.silica/*
!.silica/tools/
.silica/tools/_silica_toolspec.py
.silica/tools/__pycache__/
```

This allows `.silica/tools/` to be tracked while ignoring workspace files and generated helpers.

## Remote Deployment

When using `silica remote`:

- **Project tools** are automatically synced with `silica remote sync` since they're part of the repository
- **Personal tools** are selected during workspace creation via an interactive wizard

### Initial Tool Setup (During Create)

When you run `silica remote create`, you'll be prompted to select which personal tools to copy:

```bash
# Interactive tool selection (default)
silica remote create -w agent

# Copy all personal tools without prompting
silica remote create -w agent --all-tools

# Skip tool selection
silica remote create -w agent --no-tools
```

The wizard displays your personal tools and lets you choose which ones to copy:

```
Personal Tools Selection
Select which personal tools to copy to the remote workspace.

  #   Tool          Description
  1   hello_world   Say hello to someone.
  2   weather       Get current weather and forecast for a location.
  3   github        11 tools: github_list_prs, github_view_pr...

Options:
  • Enter tool numbers separated by commas (e.g., 1,3,5)
  • Enter 'all' to select all tools
  • Enter 'none' or press Enter to skip

Select tools: 2,3
```

### Updating Tools Later

After workspace creation, use `sync-tools` to update or add tools:

```bash
# List available personal tools
silica remote sync-tools -w agent --list

# Sync specific tools
silica remote sync-tools -w agent -t weather -t github

# Sync all personal tools
silica remote sync-tools -w agent --all
```

## Example: GitHub Tools

The silica project includes an example of migrated GitHub tools in `.silica/tools/github.py`. This multi-tool file provides:

- `github_list_prs` - List pull requests
- `github_view_pr` - View PR details
- `github_list_issues` - List issues
- `github_view_issue` - View issue details
- `github_api` - Make generic API requests
- `github_pr_comments` - Get PR comments
- `github_workflow_runs` - List workflow runs
- And more...

### Using Multi-Tool Files

Multi-tool files return an array of tool specs from `--toolspec` and use subcommands:

```bash
# Get all tool specs
.silica/tools/github.py --toolspec

# Run a specific command
.silica/tools/github.py list-prs --limit 5
```

The agent automatically routes tool calls to the correct subcommand based on the tool name (e.g., `github_list_prs` → `github.py list-prs`).

## Tool Discovery

Use `toolbox_list` to see all available tools from both locations:

```
**Tool Directories:**
  Personal: /home/user/.silica/tools
  Project: /path/to/project/.silica/tools

Found 5 user tool(s):

**github_list_prs** [project] [OK]
  Description: List pull requests in a GitHub repository.
  Category: development

**weather** [OK]
  Description: Get current weather and forecast for a location.
  Category: utility
```

Tools marked with `[project]` come from the project-local directory.
