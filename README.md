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

For detailed deployment information, see the [Raspberry Pi Deployment Guide](docs/RASPBERRY_PI_DEPLOYMENT.md).

**Note**: The package name is `pysilica` but the CLI command and import name is `silica`.

### Requirements

- **Python**: 3.11 or higher (required)
- **Package Manager**: `uv` (recommended) or `pip`

For complete installation instructions, see [docs/INSTALLATION.md](docs/INSTALLATION.md).

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

## 🤖 Supported Agents

Silica uses a [YAML-based agent configuration system](docs/YAML_AGENTS.md) for easy extensibility. Each agent is configured with its installation commands and runtime requirements.

### Adding Custom Agents

You can easily add custom agents by creating YAML configuration files. See the [YAML Agents Documentation](docs/YAML_AGENTS.md) for details.

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

# Sync with cache clearing to ensure latest versions
silica sync -w assistant --clear-cache

# Check status of a specific workspace
silica status -w assistant

# Connect to a specific workspace's agent
silica agent -w assistant

# Send a message to the workspace's agent
silica tell "Please analyze this code" -w assistant
```

### Managing Agent Types

```bash
# List all available agent types (during workspace creation)
silica create --help  # Shows available agents

# Set global default agent type
silica config set-default-agent aider

# View current global default
silica config get default_agent

# List all configuration including default agent
silica config list
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