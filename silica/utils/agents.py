"""Agent configuration and command generation for silica.

Simplified for tight coupling with heare-developer (hdev).
"""

from typing import Dict, Any, Optional
from pathlib import Path

from silica.utils.agent_yaml import load_agent_config


def validate_agent_type(agent_type: str) -> bool:
    """Validate that an agent type is supported.

    Note: Now only supports hdev, but kept for backward compatibility.
    """
    return agent_type == "hdev"


def generate_agent_command(agent_type: str, workspace_config: Dict[str, Any]) -> str:
    """Generate the command to run hdev agent.

    Args:
        agent_type: Type of agent (ignored, always uses hdev)
        workspace_config: Workspace-specific configuration

    Returns:
        Command string to execute hdev
    """
    # Always load hdev configuration regardless of agent_type parameter
    agent_config = load_agent_config("hdev")
    if not agent_config:
        raise ValueError("Could not load hdev agent configuration")

    # Get agent-specific configuration from workspace config
    agent_settings = workspace_config.get("agent_config", {})

    # Build command - always use hdev
    command_parts = [
        "uv",
        "run",
        "hdev",
    ]

    # Add default arguments from YAML configuration
    if agent_config.default_args:
        command_parts.extend(agent_config.default_args)

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


def get_default_workspace_agent_config(agent_type: str = "hdev") -> Dict[str, Any]:
    """Get default agent configuration for a workspace.

    Args:
        agent_type: Type of agent (ignored, always returns hdev config)

    Returns:
        Default hdev configuration dictionary
    """
    return {"agent_type": "hdev", "agent_config": {"flags": [], "args": {}}}


def update_workspace_with_agent(
    workspace_config: Dict[str, Any],
    agent_type: str = "hdev",
    agent_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update workspace configuration with agent settings.

    Args:
        workspace_config: Existing workspace configuration
        agent_type: Type of agent (ignored, always uses hdev)
        agent_config: Optional agent-specific configuration

    Returns:
        Updated workspace configuration with hdev settings
    """
    updated_config = workspace_config.copy()
    updated_config["agent_type"] = "hdev"  # Always hdev

    if agent_config:
        updated_config["agent_config"] = agent_config
    elif "agent_config" not in updated_config:
        # Set default hdev config if none exists
        default_config = get_default_workspace_agent_config("hdev")
        updated_config["agent_config"] = default_config["agent_config"]

    return updated_config


def generate_agent_script(workspace_config: Dict[str, Any]) -> str:
    """Generate the AGENT.sh script content for hdev agent.

    Args:
        workspace_config: Workspace configuration containing agent settings

    Returns:
        Generated AGENT.sh script content for hdev
    """
    # Generate the hdev command
    agent_command = generate_agent_command("hdev", workspace_config)

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

# Change to the code directory and start heare-developer
cd "${{TOP}}/code"
echo "Starting heare-developer (hdev) from $(pwd) at $(date)"
{agent_command} || echo "Agent exited with status $? at $(date)"

# If the agent exits, keep the shell open for debugging in tmux
echo "Agent process has ended. Keeping tmux session alive."
"""

    # Format the template with hdev command
    script_content = template.format(agent_command=agent_command)

    return script_content
