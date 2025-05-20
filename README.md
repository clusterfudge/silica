# Silica: Multi-Workspace Management for Agents

Silica is a command-line tool for creating and managing agent workspaces on top of piku.

## What's New: Multi-Workspace Support

Silica now supports managing multiple concurrent workspaces from the same repository. This allows you to:

1. Create and maintain multiple agent workspaces with different configurations
2. Switch between workspaces easily without having to recreate them
3. Track configurations for all workspaces in a single repository

## Key Features

- **Workspace Management**: Create, list, and manage multiple agent workspaces
- **Default Workspace**: Set a preferred workspace as default for easier command execution
- **Workspace-specific Configuration**: Each workspace maintains its own settings

## Usage

### Creating Workspaces

```bash
# Create a default workspace named 'agent'
silica create

# Create a workspace with a custom name
silica create -w assistant
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
  assistant:
    piku_connection: piku
    app_name: assistant-repo-name
    branch: feature-branch
```

## Compatibility

This update maintains backward compatibility with existing silica workspaces. When you run commands with the updated version:

1. Existing workspaces are automatically migrated to the new format
2. The behavior of commands without specifying a workspace remains the same
3. Old script implementations that expect workspace-specific configuration will continue to work