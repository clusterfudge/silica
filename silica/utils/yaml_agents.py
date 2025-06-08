"""YAML-based agent configuration system replacing the old Python-based system."""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from .agent_yaml import load_agent_config, list_built_in_agents


def get_supported_agents() -> List[str]:
    """Get list of supported agent names."""
    return list_built_in_agents()


def validate_agent_type(agent_type: str) -> bool:
    """Validate that an agent type is supported."""
    return agent_type in get_supported_agents()


def get_agent_description(agent_type: str) -> str:
    """Get description for an agent."""
    config = load_agent_config(agent_type)
    return config.description if config else f"Unknown agent: {agent_type}"


def get_default_workspace_agent_config(agent_type: str) -> Dict[str, Any]:
    """Get default agent configuration for a workspace."""
    if not validate_agent_type(agent_type):
        raise ValueError(f"Unsupported agent type: {agent_type}")

    return {"agent_type": agent_type, "agent_config": {"flags": [], "args": {}}}


def update_workspace_with_agent(
    workspace_config: Dict[str, Any],
    agent_type: str,
    agent_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update workspace configuration with agent settings."""
    if not validate_agent_type(agent_type):
        raise ValueError(f"Unsupported agent type: {agent_type}")

    updated_config = workspace_config.copy()
    updated_config["agent_type"] = agent_type

    if agent_config:
        updated_config["agent_config"] = agent_config
    elif "agent_config" not in updated_config:
        default_config = get_default_workspace_agent_config(agent_type)
        updated_config["agent_config"] = default_config["agent_config"]

    return updated_config


def generate_agent_runner_script(
    workspace_name: str, workspace_config: Dict[str, Any]
) -> str:
    """Generate a standalone agent runner script for a workspace.

    This replaces the old AGENT.sh template system with a Python script that
    embeds the agent configuration to avoid import dependencies.
    """
    # Get agent type from workspace config
    agent_type = workspace_config.get("agent_type", "hdev")

    # Load the agent's YAML configuration
    agent_config = load_agent_config(agent_type)
    if not agent_config:
        raise ValueError(f"Could not load configuration for agent: {agent_type}")

    # Convert agent config to dict for embedding
    agent_config_dict = {
        "name": agent_config.name,
        "description": agent_config.description,
        "install": {
            "commands": agent_config.install_commands,
            "fallback_commands": agent_config.fallback_install_commands,
            "check_command": agent_config.check_command,
        },
        "launch": {
            "command": agent_config.launch_command,
            "default_args": agent_config.default_args,
        },
        "dependencies": agent_config.dependencies,
    }

    # Load the template
    template_path = Path(__file__).parent / "templates" / "AGENT_runner.py.template"
    with open(template_path, "r") as f:
        template = f.read()

    # Format the template with embedded configuration
    script_content = template.format(
        workspace_name=workspace_name,
        agent_type=agent_type,
        agent_config_yaml=json.dumps(agent_config_dict, indent=4),
        workspace_config_json=json.dumps(workspace_config, indent=4),
    )

    return script_content


# Backward compatibility functions for existing code
def generate_agent_command(agent_type: str, workspace_config: Dict[str, Any]) -> str:
    """Generate command for backward compatibility."""
    from .agent_yaml import generate_launch_command

    agent_config = load_agent_config(agent_type)
    if not agent_config:
        raise ValueError(f"Unsupported agent type: {agent_type}")

    return generate_launch_command(agent_config, workspace_config)


def generate_agent_script(workspace_config: Dict[str, Any]) -> str:
    """Generate agent script for backward compatibility."""
    workspace_name = workspace_config.get("app_name", "unknown")
    return generate_agent_runner_script(workspace_name, workspace_config)
