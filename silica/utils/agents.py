"""Agent configuration and command generation for silica."""

from typing import Dict, Any, Optional, List
from pathlib import Path

from silica.utils.yaml_agents import get_supported_agents
from silica.utils.agent_yaml import load_agent_config


def validate_agent_type(agent_type: str) -> bool:
    """Validate that an agent type is supported."""
    return agent_type in get_supported_agents()


def generate_agent_command(agent_type: str, workspace_config: Dict[str, Any]) -> str:
    """Generate the command to run a specific agent.

    Args:
        agent_type: Type of agent to run
        workspace_config: Workspace-specific configuration

    Returns:
        Command string to execute the agent
    """
    agent_config = load_agent_config(agent_type)
    if not agent_config:
        raise ValueError(f"Unsupported agent type: {agent_type}")

    # Get agent-specific configuration from workspace config
    agent_settings = workspace_config.get("agent_config", {})

    # Build command
    command_parts = ["uv", "run", agent_config.launch_command.split()[-1]]  # Get just the command name

    # Add default arguments from YAML configuration
    if agent_config.default_args:
        command_parts.extend(agent_config.default_args)

    # Add model selection logic for agents that support multiple models
    if agent_type in ["aider", "cline"]:
        model_arg = _get_model_argument(agent_type)
        if model_arg:
            command_parts.extend(model_arg)

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


def _get_model_argument(agent_type: str) -> Optional[List[str]]:
    """Get model selection arguments based on available API keys.
    
    Args:
        agent_type: The agent type (aider or cline)
        
    Returns:
        List of command arguments for model selection, or None
    """
    import os
    
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    
    if agent_type == "aider":
        # Aider model selection priority: GPT-4 > Claude > default
        if has_openai:
            return ["--model", "gpt-4"]
        elif has_anthropic:
            return ["--model", "claude-3-5-sonnet-20241022"]
        # If no API keys, let aider use its default
        return None
        
    elif agent_type == "cline":
        # Cline model selection priority: Claude > GPT-4 > default
        if has_anthropic:
            return ["--model", "claude-3-5-sonnet-20241022"]
        elif has_openai:
            return ["--model", "gpt-4"]
        # If no API keys, let cline use its default
        return None
        
    return None


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
source $HOME/.piku/envs/${{APP_NAME}}/ENV  # could be LIVE_ENV?

# Synchronize dependencies
cd "${{TOP}}"
uv sync

# Change to the code directory and start the agent
cd "${{TOP}}/code"
echo "Starting the {agent_type} agent from $(pwd) at $(date)"
{agent_command} || echo "Agent exited with status $? at $(date)"

# If the agent exits, keep the shell open for debugging in tmux
echo "Agent process has ended. Keeping tmux session alive."
"""

    # Format the template with agent-specific values
    script_content = template.format(agent_type=agent_type, agent_command=agent_command)

    return script_content