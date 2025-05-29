"""Agent configuration and command generation for silica."""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentConfig:
    """Configuration for a specific agent type."""

    name: str
    command: str
    description: str
    default_args: Dict[str, Any]
    required_dependencies: List[str]


# Define supported agents
SUPPORTED_AGENTS = {
    "hdev": AgentConfig(
        name="hdev",
        command="hdev",
        description="Heare Developer - autonomous coding agent",
        default_args={"flags": ["--dwr"], "args": {"persona": "autonomous_engineer"}},
        required_dependencies=["heare-developer"],
    ),
    "claude-code": AgentConfig(
        name="claude-code",
        command="claude-code",
        description="Claude Code - Anthropic's coding assistant",
        default_args={"flags": [], "args": {}},
        required_dependencies=["claude-code"],
    ),
    "openai-codex": AgentConfig(
        name="openai-codex",
        command="openai-codex",
        description="OpenAI Codex - AI coding assistant",
        default_args={"flags": [], "args": {}},
        required_dependencies=["openai-codex"],
    ),
    "cline": AgentConfig(
        name="cline",
        command="cline",
        description="Cline - AI coding assistant with VS Code integration",
        default_args={"flags": [], "args": {}},
        required_dependencies=["cline"],
    ),
    "aider": AgentConfig(
        name="aider",
        command="aider",
        description="AI pair programming in your terminal",
        default_args={"flags": ["--auto-commits"], "args": {}},
        required_dependencies=["aider-chat"],
    ),
}


def get_supported_agents() -> List[str]:
    """Get list of supported agent names."""
    return list(SUPPORTED_AGENTS.keys())


def get_agent_config(agent_type: str) -> Optional[AgentConfig]:
    """Get configuration for a specific agent type."""
    return SUPPORTED_AGENTS.get(agent_type)


def validate_agent_type(agent_type: str) -> bool:
    """Validate that an agent type is supported."""
    return agent_type in SUPPORTED_AGENTS


def generate_agent_command(agent_type: str, workspace_config: Dict[str, Any]) -> str:
    """Generate the command to run a specific agent.

    Args:
        agent_type: Type of agent to run
        workspace_config: Workspace-specific configuration

    Returns:
        Command string to execute the agent
    """
    agent_config = get_agent_config(agent_type)
    if not agent_config:
        raise ValueError(f"Unsupported agent type: {agent_type}")

    # Get agent-specific configuration from workspace config
    agent_settings = workspace_config.get("agent_config", {})

    # Build command
    command_parts = ["uv", "run", agent_config.command]

    # Add default flags from agent definition
    default_flags = agent_config.default_args.get("flags", [])
    command_parts.extend(default_flags)

    # Add default arguments from agent definition
    default_args = agent_config.default_args.get("args", {})
    for key, value in default_args.items():
        if value is True:
            command_parts.append(f"--{key}")
        elif value is not False and value is not None:
            command_parts.extend([f"--{key}", str(value)])

    # Add custom flags from workspace config
    custom_flags = agent_settings.get("flags", [])
    command_parts.extend(custom_flags)

    # Add custom arguments from workspace config
    custom_args = agent_settings.get("args", {})
    for key, value in custom_args.items():
        if value is True:
            command_parts.append(f"--{key}")
        elif value is not False and value is not None:
            command_parts.extend([f"--{key}", str(value)])

    return " ".join(command_parts)


def get_default_workspace_agent_config(agent_type: str) -> Dict[str, Any]:
    """Get default agent configuration for a workspace.

    Args:
        agent_type: Type of agent

    Returns:
        Default configuration dictionary for the agent
    """
    if not validate_agent_type(agent_type):
        raise ValueError(f"Unsupported agent type: {agent_type}")

    return {"agent_type": agent_type, "agent_config": {"flags": [], "args": {}}}


def update_workspace_with_agent(
    workspace_config: Dict[str, Any],
    agent_type: str,
    agent_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update workspace configuration with agent settings.

    Args:
        workspace_config: Existing workspace configuration
        agent_type: Type of agent to configure
        agent_config: Optional agent-specific configuration

    Returns:
        Updated workspace configuration
    """
    if not validate_agent_type(agent_type):
        raise ValueError(f"Unsupported agent type: {agent_type}")

    updated_config = workspace_config.copy()
    updated_config["agent_type"] = agent_type

    if agent_config:
        updated_config["agent_config"] = agent_config
    elif "agent_config" not in updated_config:
        # Set default agent config if none exists
        default_config = get_default_workspace_agent_config(agent_type)
        updated_config["agent_config"] = default_config["agent_config"]

    return updated_config


def generate_agent_script(workspace_config: Dict[str, Any]) -> str:
    """Generate the AGENT.sh script content for a specific workspace configuration.

    Args:
        workspace_config: Workspace configuration containing agent settings

    Returns:
        Generated AGENT.sh script content
    """
    # Get agent type, default to hdev for backward compatibility
    agent_type = workspace_config.get("agent_type", "hdev")

    # Generate the agent command
    agent_command = generate_agent_command(agent_type, workspace_config)

    # Load the template
    try:
        template_path = Path(__file__).parent / "templates" / "AGENT.sh.template"
        with open(template_path, "r") as f:
            template = f.read()
    except FileNotFoundError:
        # Fallback template if file doesn't exist
        template = """#!/usr/bin/env bash
# Get the directory where this script is located
TOP=$(cd $(dirname $0) && pwd)
APP_NAME=$(basename $TOP)

# NOTE: piku-specific
# source environment variables
set -a
source $HOME/.piku/envs/${APP_NAME}/ENV  # could be LIVE_ENV?

# Synchronize dependencies
cd "${TOP}"
uv sync

# Change to the code directory and start the agent
cd "${TOP}/code"
echo "Starting the {agent_type} agent from $(pwd) at $(date)"
{agent_command} || echo "Agent exited with status $? at $(date)"

# If the agent exits, keep the shell open for debugging in tmux
echo "Agent process has ended. Keeping tmux session alive."
"""

    # Format the template with agent-specific values
    script_content = template.format(agent_type=agent_type, agent_command=agent_command)

    return script_content
