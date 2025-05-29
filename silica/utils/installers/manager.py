"""Agent installation manager for silica."""

import importlib
from typing import Dict, Optional, List
from rich.console import Console

from silica.utils.agents import get_supported_agents

console = Console()


class AgentInstaller:
    """Manages installation of different agent types."""

    def __init__(self):
        self._installers = {}
        self._load_installers()

    def _load_installers(self):
        """Load all available agent installers."""
        agent_to_module = {
            "hdev": "hdev",
            "aider": "aider",
            "claude-code": "claude_code",
            "cline": "cline",
            "openai-codex": "openai_codex",
        }

        for agent_name, module_name in agent_to_module.items():
            try:
                module = importlib.import_module(
                    f"silica.utils.installers.{module_name}"
                )
                self._installers[agent_name] = module
            except ImportError as e:
                console.print(
                    f"[yellow]Warning: Could not load installer for {agent_name}: {e}[/yellow]"
                )

    def is_agent_installed(self, agent_type: str) -> bool:
        """Check if an agent is already installed.

        Args:
            agent_type: The type of agent to check

        Returns:
            True if the agent is installed, False otherwise
        """
        if agent_type not in self._installers:
            return False

        try:
            return self._installers[agent_type].is_installed()
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
        if agent_type not in self._installers:
            console.print(
                f"[red]✗ No installer available for agent type: {agent_type}[/red]"
            )
            return False

        try:
            return self._installers[agent_type].install()
        except Exception as e:
            console.print(f"[red]✗ Error installing {agent_type}: {e}[/red]")
            return False

    def get_install_command(self, agent_type: str) -> Optional[str]:
        """Get the installation command for an agent.

        Args:
            agent_type: The type of agent

        Returns:
            Installation command string, or None if not available
        """
        if agent_type not in self._installers:
            return None

        try:
            return self._installers[agent_type].get_install_command()
        except Exception:
            return None

    def check_all_agents(self) -> Dict[str, bool]:
        """Check installation status of all supported agents.

        Returns:
            Dictionary mapping agent names to installation status
        """
        status = {}
        for agent_type in get_supported_agents():
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
installer = AgentInstaller()
