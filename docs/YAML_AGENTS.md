# Heare-Developer Agent Configuration

## Overview

Silica is tightly integrated with **heare-developer (hdev)**, an autonomous coding agent. This document describes how hdev is configured and integrated into the Silica workflow.

## Agent Configuration

The hdev agent is configured via a YAML file at `silica/agents/hdev.yaml`:

```yaml
name: "hdev"
description: "Heare Developer - autonomous coding agent"
install:
  commands:
    - "uv add heare-developer"
  fallback_commands:
    - "pip install heare-developer"
  check_command: "hdev --help"
launch:
  command: "uv run hdev"
  default_args:
    - "--dwr"
    - "--persona"
    - "autonomous_engineer"
dependencies:
  - "heare-developer"
environment:
  required:
    - name: "ANTHROPIC_API_KEY"
      description: "Anthropic API key for Claude access"
    - name: "BRAVE_SEARCH_API_KEY" 
      description: "Brave Search API key for web search functionality"
    - name: "GH_TOKEN"
      description: "GitHub token for repository access"
  recommended:
    - name: "OPENAI_API_KEY"
      description: "OpenAI API key for additional model access (optional)"
```

## Key Features

### Autonomous Operation
- **`--dwr` (Do What's Required)**: Enables fully autonomous operation mode
- **`--persona autonomous_engineer`**: Sets the agent's behavior profile for engineering tasks

### Integrated Capabilities
- **Claude AI Integration**: Primary model access via Anthropic API
- **Web Search**: Real-time information via Brave Search API
- **GitHub Integration**: Repository operations via GitHub token
- **Multi-model Support**: Optional OpenAI model access

## Installation and Deployment

### Automatic Installation
Hdev is automatically installed when creating workspaces through:

1. **Workspace Dependencies**: Added to `pyproject.toml` of each workspace
2. **UV Sync**: Installed via `uv sync` during workspace setup
3. **Verification**: Checked for availability before running

### Environment Setup
Required environment variables are automatically configured during workspace creation through the Silica configuration system.

## Workspace Integration

### Creation
```bash
# Create workspace with hdev (default)
silica create

# Create named workspace with hdev
silica create -w my-project
```

### Customization
You can customize hdev behavior per workspace by modifying the agent configuration:

```yaml
# Example workspace config with custom hdev settings
agent_type: hdev
agent_config:
  flags: 
    - "--persona"
    - "code_reviewer"  # Different persona
    - "--verbose"
  args:
    timeout: 300
```

### Running
```bash
# Setup workspace environment
silica we setup

# Run hdev agent
silica we run

# Check workspace status
silica we status
```

## Configuration Fields

### Launch Configuration
- **command**: `uv run hdev` - Uses the workspace environment
- **default_args**: Standard flags for optimal autonomous operation

### Environment Variables

#### Required
- **ANTHROPIC_API_KEY**: Claude model access for primary AI capabilities
- **BRAVE_SEARCH_API_KEY**: Web search for real-time information
- **GH_TOKEN**: GitHub operations for repository management

#### Recommended  
- **OPENAI_API_KEY**: Additional model access for enhanced capabilities

### Dependencies
- **heare-developer**: The main package, installed via workspace dependencies

## Architecture Benefits

1. **Tight Integration**: Hdev is part of workspace dependencies, ensuring version consistency
2. **Autonomous by Default**: Configured for fully autonomous operation out of the box
3. **Environment Aware**: Automatically detects and uses available API keys and services
4. **Workspace Isolated**: Each workspace has its own hdev configuration and environment
5. **Maintenance Free**: No need to manage multiple agent types or configurations

## Migration Notes

If you have existing Silica workspaces with other agent types, they will automatically use hdev when updated. The workspace environment commands are backward compatible and will work seamlessly with existing configurations.

## Advanced Configuration

### Custom Personas
You can customize hdev's behavior by changing the persona:

```bash
# Modify workspace config to use different persona
silica config set agent_config.flags='["--dwr", "--persona", "code_reviewer"]'
```

### Performance Tuning
Adjust hdev settings for specific project needs:

```yaml
agent_config:
  flags:
    - "--dwr"
    - "--persona"
    - "autonomous_engineer"
    - "--max-tokens"
    - "4000"
  args:
    timeout: 600
```

## Troubleshooting

### Installation Issues
If hdev installation fails:
1. Check that `uv` is available: `uv --version`
2. Manually install: `uv add heare-developer`
3. Verify installation: `uv run hdev --help`

### Environment Issues
If hdev can't access required services:
1. Check environment variables: `silica we status`
2. Configure missing keys: `silica config setup`
3. Verify API key access by testing the services directly

### Runtime Issues
If hdev doesn't start properly:
1. Check workspace status: `silica we status --json`
2. Review workspace logs in the tmux session
3. Manually run setup: `silica we setup`

For more detailed troubleshooting, see [TESTING_STRATEGY.md](TESTING_STRATEGY.md).