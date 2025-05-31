# YAML-based Agent Configuration System

## Overview

Silica uses a YAML-based configuration system for defining AI coding agents. This allows for declarative agent configuration without writing Python code, making it easy to add new agents or customize existing ones.

## Agent Configuration Format

Each agent is defined by a YAML file in the `silica/agents/` directory with the following structure:

```yaml
name: "agent-name"
description: "Human-readable description of the agent"
install:
  commands:
    - "primary installation command"
    - "additional installation command if needed"
  fallback_commands:
    - "fallback installation command if primary fails"
  check_command: "command to verify installation"
launch:
  command: "uv run agent-command"
  default_args:
    - "--flag1"
    - "--key"
    - "value"
dependencies:
  - "package-name"
environment:
  required:
    - name: "API_KEY"
      description: "Required API key for the service"
    - name: "GITHUB_TOKEN"
      description: "GitHub token for repository access"
  recommended:
    - name: "OPTIONAL_KEY"
      description: "Optional API key for enhanced features"
```

## Built-in Agent Examples

### hdev (Heare Developer)
```yaml
name: "hdev"
description: "Heare Developer - autonomous coding agent"
install:
  commands:
    - "pip install heare-developer"
  fallback_commands:
    - "uv add heare-developer"
  check_command: "hdev --version"
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
    - name: "GITHUB_TOKEN"
      description: "GitHub token for repository access"
  recommended:
    - name: "OPENAI_API_KEY"
      description: "OpenAI API key for additional model access (optional)"
```

### aider (AI Pair Programming)
```yaml
name: "aider"
description: "AI pair programming in your terminal"
install:
  commands:
    - "pip install aider-chat"
  check_command: "aider --version"
launch:
  command: "uv run aider"
  default_args:
    - "--auto-commits"
dependencies:
  - "aider-chat"
environment:
  required:
    - name: "GITHUB_TOKEN"
      description: "GitHub token for repository access"
  recommended:
    - name: "OPENAI_API_KEY"
      description: "OpenAI API key for GPT model access"
    - name: "ANTHROPIC_API_KEY"
      description: "Anthropic API key for Claude model access"
```

## How It Works

### 1. Agent Discovery
The system automatically discovers all `.yaml` files in the `silica/agents/` directory.

### 2. Configuration Loading
When an agent is selected, its YAML configuration is loaded and validated.

### 3. Installation
If the agent isn't installed, the system runs the installation commands:
1. Try primary installation commands first
2. If those fail, try fallback commands
3. Verify installation using the check command

### 4. Script Generation
A standalone Python runner script is generated with the agent configuration embedded. This script:
- Loads environment variables from piku
- Synchronizes dependencies with `uv sync`
- Ensures the agent is installed
- Launches the agent with the correct configuration

### 5. Execution
The generated script runs in the workspace environment without requiring any imports from the silica package.

## Creating Custom Agents

To add a custom agent:

1. Create a new YAML file: `silica/agents/my-agent.yaml`
2. Define the configuration following the format above
3. The agent will automatically be available in silica commands

Example custom agent:
```yaml
name: "my-custom-agent"
description: "My custom AI coding agent"
install:
  commands:
    - "pip install my-agent-package"
  check_command: "my-agent --version"
launch:
  command: "uv run my-agent"
  default_args:
    - "--verbose"
    - "--mode"
    - "interactive"
dependencies:
  - "my-agent-package"
```

## Configuration Fields

### Required Fields
- `name`: Unique identifier for the agent
- `description`: Human-readable description
- `launch.command`: Command to launch the agent

### Optional Fields
- `install.commands`: Installation commands (default: empty)
- `install.fallback_commands`: Fallback installation commands (default: empty)
- `install.check_command`: Command to verify installation (default: empty)
- `launch.default_args`: Default command-line arguments (default: empty)
- `dependencies`: Package dependencies (default: empty)
- `environment.required`: Required environment variables (default: empty)
- `environment.recommended`: Recommended environment variables (default: empty)

### Environment Variables
Environment variables are specified with a name and description:

```yaml
environment:
  required:
    - name: "API_KEY"
      description: "API key for the service"
  recommended:
    - name: "OPTIONAL_KEY" 
      description: "Optional enhancement key"
```

**Required vs Recommended:**
- **Required**: Agent may not function without these variables
- **Recommended**: Agent works but with limited functionality

### Installation Behavior
- If no installation commands are provided, the agent is assumed to be pre-installed
- If no check command is provided, installation verification is skipped
- Commands are executed using shell (`shell=True`)
- Installation has a 5-minute timeout per command

### Launch Behavior
- The launch command should typically start with `uv run` to use the project environment
- Default arguments are added before any workspace-specific customizations
- Workspace-specific flags and arguments can be added via the CLI

## Workspace Customization

Each workspace can customize agent behavior by adding flags and arguments:

```bash
# Add custom flags
silica agents configure my-agent -w my-workspace

# Set agent for workspace
silica agents set my-agent -w my-workspace
```

This creates workspace-specific configuration that gets merged with the agent's default configuration.

## Architecture Benefits

1. **Declarative**: Configuration is data, not code
2. **Extensible**: Easy to add new agents without Python knowledge
3. **Maintainable**: Clear separation of configuration and logic
4. **Portable**: Generated scripts are self-contained
5. **Testable**: Easy to validate YAML configurations

## Migration from Python-based System

The YAML system is fully backward compatible:
- All existing functionality is preserved
- Old `AGENT.sh` scripts are replaced with `AGENT_runner.py`
- Existing workspace configurations continue to work
- No user-facing breaking changes
### Advanced Configuration
```bash
# Configure agent with custom settings
silica agents configure aider -w my-project

# View detailed agent configuration
silica agents show -w my-project

# Setup silica with preferred default agent
silica config setup
```

### Environment Variable Management
```bash
# List agents with environment status
silica agents list

# View detailed agent configuration (includes env vars)
silica agents show --workspace my-project
```