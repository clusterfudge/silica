# Silica: Multi-Workspace Management for Agents

Silica is a command-line tool for creating and managing agent workspaces on top of piku.

## What's New: Multi-Workspace Support

Silica now supports managing multiple concurrent workspaces from the same repository. This allows you to:

1. Create and maintain multiple agent workspaces with different configurations
2. Switch between workspaces easily without having to recreate them
3. Track configurations for all workspaces in a single repository

## Key Features

- **Multiple Agent Support**: Support for different AI coding agents (hdev, claude-code, openai-codex, cline, aider)
- **Workspace Management**: Create, list, and manage multiple agent workspaces
- **Default Workspace**: Set a preferred workspace as default for easier command execution
- **Workspace-specific Configuration**: Each workspace maintains its own settings including agent type

## Usage

### Creating Workspaces

```bash
# Create a default workspace named 'agent' using global default agent
silica create

# Create a workspace with a custom name and different agent
silica create -w assistant -a aider

# Create workspace with specific agent type
silica create -w cline-workspace -a cline

# The agent type is determined by (in order of priority):
# 1. -a/--agent flag if provided
# 2. Global default agent setting
# 3. Fallback to 'hdev' if no global default set
```

### Managing Workspaces

```bash
# List all configured workspaces
silica workspace list

# View the current default workspace
silica workspace get-default

# Set a different workspace as default
silica workspace set-default assistant
```

### Working with Specific Workspaces

Most commands accept a `-w/--workspace` flag to specify which workspace to target:

```bash
# Sync a specific workspace
silica sync -w assistant

# Check status of a specific workspace
silica status -w assistant

# Connect to a specific workspace's agent
silica agent -w assistant
```

### Managing Agent Types

```bash
# List all supported agent types
silica agents list

# View agent configuration for all workspaces
silica agents status

# Show detailed agent configuration for current workspace
silica agents show

# Change agent type for a workspace
silica agents set cline -w my-workspace

# Configure agent with custom settings
silica agents configure cline -w my-workspace

# Set global default agent type
silica agents set-default aider

# View current global default
silica agents get-default
```

### Destroying Workspaces

```bash
# Destroy a specific workspace
silica destroy -w assistant
```

## Configuration

Silica now stores workspace configurations in `.silica/config.yaml` using a nested structure:

```yaml
default_workspace: agent
workspaces:
  agent:
    piku_connection: piku
    app_name: agent-repo-name
    branch: main
    agent_type: hdev
    agent_config:
      flags: []
      args: {}
  assistant:
    piku_connection: piku
    app_name: assistant-repo-name
    branch: feature-branch
    agent_type: cline
    agent_config:
      flags: []
      args: {}
```

## Compatibility

This update maintains backward compatibility with existing silica workspaces. When you run commands with the updated version:

1. Existing workspaces are automatically migrated to the new format
2. The behavior of commands without specifying a workspace remains the same
3. Old script implementations that expect workspace-specific configuration will continue to work