"""YAML-based agent installation manager for silica."""

from typing import Dict, List
from rich.console import Console

from .agent_yaml import (
    load_agent_config,
    install_agent,
    is_agent_installed,
    list_built_in_agents,
)

console = Console()


class YamlAgentInstaller:
    """Manages installation of different agent types using YAML configurations."""

    def is_agent_installed(self, agent_type: str) -> bool:
        """Check if an agent is already installed.

        Args:
            agent_type: The type of agent to check

        Returns:
            True if the agent is installed, False otherwise
        """
        agent_config = load_agent_config(agent_type)
        if not agent_config:
            console.print(f"[red]✗ Unknown agent type: {agent_type}[/red]")
            return False

        try:
            return is_agent_installed(agent_config)
        except Exception as e:
            console.print(
                f"[yellow]Warning: Error checking {agent_type} installation: {e}[/yellow]"
            )
            return False

    def install_agent(self, agent_type: str) -> bool:
        """Install an agent if not already installed.

        Args:
            agent_type: The type of agent to install

        Returns:
            True if installation successful or already installed, False otherwise
        """
        agent_config = load_agent_config(agent_type)
        if not agent_config:
            console.print(f"[red]✗ Unknown agent type: {agent_type}[/red]")
            return False

        try:
            return install_agent(agent_config)
        except Exception as e:
            console.print(f"[red]✗ Error installing {agent_type}: {e}[/red]")
            return False

    def get_install_command(self, agent_type: str) -> str:
        """Get the installation command for an agent.

        Args:
            agent_type: The type of agent

        Returns:
            Installation command string, or empty string if not available
        """
        agent_config = load_agent_config(agent_type)
        if not agent_config:
            return ""

        # Return the first install command as the primary one
        if agent_config.install_commands:
            return agent_config.install_commands[0]

        return ""

    def check_all_agents(self) -> Dict[str, bool]:
        """Check installation status of all supported agents.

        Returns:
            Dictionary mapping agent names to installation status
        """
        status = {}
        for agent_type in list_built_in_agents():
            status[agent_type] = self.is_agent_installed(agent_type)
        return status

    def install_required_agents(self, agent_types: List[str]) -> Dict[str, bool]:
        """Install multiple agents.

        Args:
            agent_types: List of agent types to install

        Returns:
            Dictionary mapping agent names to installation success status
        """
        results = {}
        for agent_type in agent_types:
            console.print(f"\n[bold]Processing {agent_type}...[/bold]")
            results[agent_type] = self.install_agent(agent_type)
        return results


# Global installer instance
installer = YamlAgentInstaller()
