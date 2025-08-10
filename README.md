# Silica: Multi-Workspace Management for Agents

Silica is a command-line tool for creating and managing agent workspaces on top of piku.

## Installation

### Quick Install

For systems with Python 3.11+:

```bash
# Using uv (recommended)
uv pip install pysilica

# Using pip
pip install pysilica
```

### Raspberry Pi Deployment

Silica automatically handles Python 3.11 installation on remote Raspberry Pi systems during workspace creation. The deployment process:

- Detects Raspberry Pi hardware
- Installs Python 3.11 via pyenv if needed
- Sets up virtual environment
- Installs Silica and dependencies
- Verifies the installation

For detailed deployment information, see the [Raspberry Pi Deployment Guide](docs/remote/RASPBERRY_PI_DEPLOYMENT.md).

**Note**: The package name is `pysilica` but the CLI command and import name is `silica`.

### Requirements

- **Python**: 3.11 or higher (required)
- **Package Manager**: `uv` (recommended) or `pip`

For complete installation instructions, see [docs/INSTALLATION.md](docs/remote/INSTALLATION.md).

## What's New: Multi-Workspace Support

Silica now supports managing multiple concurrent workspaces from the same repository. This allows you to:

1. Create and maintain multiple agent workspaces with different configurations
2. Switch between workspaces easily without having to recreate them
3. Track configurations for all workspaces in a single repository

## Key Features

- **Multiple Agent Support**: Support for different AI coding agents with YAML-based configuration
- **Workspace Management**: Create, list, and manage multiple agent workspaces
- **Default Workspace**: Set a preferred workspace as default for easier command execution
- **Immutable Workspaces**: Each workspace is tied to a specific agent type - create new workspaces for different agents

## 🤖 Integrated Agent

Silica is tightly integrated with **heare-developer (hdev)**, an autonomous coding agent that includes:

- Autonomous engineering with the `--dwr` (Do What's Required) flag
- Configurable personas for different coding styles  
- Integration with Claude for AI assistance
- Web search capabilities via Brave Search API
- GitHub integration for repository management

The agent is automatically installed when creating workspaces and configured for optimal performance.

## Usage

### Creating Workspaces

```bash
# Create a default workspace named 'agent' with heare-developer
silica create

# Create a workspace with a custom name
silica create -w assistant

# Create workspace for a specific project
silica create -w my-project
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

# Sync with cache clearing to ensure latest versions
silica sync -w assistant --clear-cache

# Check status of a specific workspace
silica status -w assistant

# Connect to a specific workspace's agent
silica agent -w assistant

# Send a message to the workspace's agent
silica tell "Please analyze this code" -w assistant
```

### Configuration Management

```bash
# View current configuration
silica config list

# Set configuration values
silica config set key=value

# Run interactive setup wizard  
silica config setup
```

### Destroying Workspaces

```bash
# Destroy a specific workspace
silica destroy -w assistant
```

## Configuration

Silica stores workspace configurations in `.silica/config.yaml` using a nested structure:

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
    agent_type: hdev
    agent_config:
      flags: ["--persona", "code_reviewer"]
      args: {}
```

## Compatibility

This update maintains backward compatibility with existing silica workspaces. When you run commands with the updated version:

1. Existing workspaces are automatically migrated to the new format
2. The behavior of commands without specifying a workspace remains the same
3. Old script implementations that expect workspace-specific configuration will continue to work