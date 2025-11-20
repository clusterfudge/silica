# Environment Variables in Remote Workspaces

This document explains how environment variables work in remote silica workspaces and how to access them in different contexts.

## Overview

Remote silica workspaces use piku for deployment. Piku manages environment variables per application and makes them available to processes it launches.

## Setting Environment Variables

Set environment variables for your workspace using piku:

```bash
# From your local machine
silica config set ANTHROPIC_API_KEY=sk-ant-api03-your-key

# Or directly via piku (from remote server)
piku config:set ANTHROPIC_API_KEY=sk-ant-api03-your-key
```

### Required Variables

- `ANTHROPIC_API_KEY` - Required for Claude AI access
- `GH_TOKEN` or `GITHUB_TOKEN` - Required for private repository access

### Optional Variables

- `BRAVE_SEARCH_API_KEY` - Enables web search functionality

## How Environment Variables Work

### Via Antennae (Recommended)

When you use `silica agent -w <workspace>`, the system:

1. Connects to the antennae webapp (running via piku with environment variables)
2. Antennae starts a tmux session with the agent
3. Environment variables are passed from antennae to the tmux session
4. Agent runs with full access to all configured variables

### Direct Shell Access

When you SSH directly to the server and try to run commands, the shell session doesn't have piku's environment variables by default.

## Working with Environment Variables in Shell

### Option 1: Load Environment Helper (Recommended)

Each workspace includes a `load_env.sh` script that loads piku environment variables:

```bash
# SSH to remote server
ssh piku@host

# Navigate to your app directory
cd ~/.piku/apps/<workspace>-<project>

# Load environment variables
source ./load_env.sh

# Verify variables are loaded
echo $ANTHROPIC_API_KEY

# Now you can run commands with environment variables available
cd code
uv run silica --dwr --persona autonomous_engineer
```

### Option 2: Use Antennae API (Best Practice)

Instead of running commands directly in the shell, use the antennae API:

```bash
# From local machine - send a command to the agent
silica tell -w <workspace> "your command here"

# Connect to the agent interactively
silica agent -w <workspace>
```

This is the preferred method because:
- Environment variables are automatically available
- Sessions are managed properly
- You get the full interactive agent experience
- No SSH access required

## Troubleshooting

### "ANTHROPIC_API_KEY environment variable not set"

This error occurs when running commands directly in a shell without loading environment variables.

**Solutions:**

1. **Use antennae** (recommended):
   ```bash
   silica agent -w <workspace>
   ```

2. **Load environment in shell**:
   ```bash
   source load_env.sh
   ```

3. **Check piku configuration**:
   ```bash
   piku config:get ANTHROPIC_API_KEY
   ```

### Environment Variables Not Loading

If `load_env.sh` doesn't work:

1. **Verify piku ENV files exist**:
   ```bash
   ls -la ~/.piku/envs/<app-name>/
   cat ~/.piku/envs/<app-name>/ENV
   ```

2. **Set variables via piku**:
   ```bash
   piku config:set ANTHROPIC_API_KEY=your-key
   ```

3. **Check app name**:
   ```bash
   # App name format is: <workspace>-<project>
   # Example: agent-myproject
   pwd  # Should show app name in path
   ```

## Best Practices

1. **Always use antennae API for agent interaction** - This ensures proper environment and session management

2. **Set variables via piku** - Use `silica config set` or `piku config:set` rather than editing ENV files directly

3. **Don't commit ENV files** - Environment variables are managed by piku, not in git

4. **Use load_env.sh for debugging** - When you need to run commands directly for troubleshooting

5. **Verify critical variables** - After setting variables, verify with `piku config:get <VAR_NAME>`

## Security Considerations

- Environment variables containing API keys are sensitive
- They're stored in piku's ENV files (not in git)
- Only accessible to the piku user on the remote server
- Passed to agent processes via environment, not command line arguments
- Not logged or exposed in process listings

## Reference

### load_env.sh Script

The `load_env.sh` script is automatically deployed to each workspace directory. It:

1. Reads piku ENV and LIVE_ENV files
2. Exports all variables to current shell
3. Validates critical variables are present
4. Provides warnings for missing recommended variables

### Environment File Locations

Piku stores environment variables in:
- `~/.piku/envs/<app-name>/ENV` - Base environment variables
- `~/.piku/envs/<app-name>/LIVE_ENV` - Runtime environment variables (overrides ENV)

Both files are loaded, with LIVE_ENV taking precedence.
