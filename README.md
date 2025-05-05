# Silica

[![PR Checks](https://github.com/clusterfudge/silica/actions/workflows/pr-checks.yml/badge.svg)](https://github.com/clusterfudge/silica/actions/workflows/pr-checks.yml)
[![PyPI version](https://badge.fury.io/py/pysilica.svg)](https://badge.fury.io/py/pysilica)
[![Python Versions](https://img.shields.io/pypi/pyversions/pysilica.svg)](https://pypi.org/project/pysilica/)

Silica is a command-line tool designed to create and manage remote environments in which coding agents can independently operate.

## What is Silica?

Silica enables you to set up isolated, fully operational remote environments for AI coding agents. These environments serve as independent workspaces where AI can:

- Execute code
- Access development tools
- Interact with version control
- Operate with proper authentication and credentials
- Maintain long-running sessions
- Work independently on specified tasks

By creating this separation between your local environment and the agent's workspace, Silica allows for more autonomous operation of AI assistants with appropriate security boundaries.

## Key Features

- **Remote Environment Creation**: Easily provision isolated environments for your AI agents
- **Credential Management**: Securely manage access to GitHub and AI APIs
- **Session Management**: Monitor and interact with active agent sessions
- **Task Management**: Assign and track work items for your agents
- **Integration with [Piku](https://github.com/piku/piku)**: Leverages Piku's simple PaaS capabilities for deployments

## Installation

Silica is available on PyPI as [`pysilica`](https://pypi.org/project/pysilica/):

```bash
pip install pysilica
```

You can also install the latest development version directly from GitHub:

```bash
pip install git+https://github.com/silica-ai/silica.git
```

## Getting Started

1. **Setup Configuration**:
   ```bash
   silica setup
   ```
   This will guide you through an interactive setup process to configure Silica.

2. **Create a Remote Environment**:
   ```bash
   silica create [name]
   ```
   Creates a new environment for your agent.

3. **Check Status**:
   ```bash
   silica status
   ```
   Shows the status of active agent sessions.

4. **Manage Tasks**:
   ```bash
   silica todos
   ```
   Manage work items for your agent.

5. **Clean Up**:
   ```bash
   silica destroy [name]
   ```
   Removes a remote environment when no longer needed.

## Configuration

Silica stores its configuration in `~/.config/silica`. You can modify settings with:

```bash
silica config:set key=value
```

Or view current configuration with:

```bash
silica config
```

## How It Works

Silica creates an isolated environment on a remote server where your agent can operate. It uses Piku as the underlying platform and sets up the necessary scaffolding for the agent to run code, access tools, and maintain state.

The remote environment includes:
- A dedicated code directory with your project files
- Proper authentication for GitHub and AI services
- A running service that maintains the agent's capabilities

## Use Cases

- **Continuous Development**: Set up an agent that can work on your codebase even when your local machine is off
- **Automated Tasks**: Deploy agents that handle routine development tasks independently
- **Collaborative Assistance**: Create environments where agents can assist multiple team members without requiring local setup

## Requirements

- Python 3.11+
- Git
- Access to a server where you can install Piku

## License

[License information]

## Contributing

[Contributing information]
