"""YAML-based agent configuration loader and validator."""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import subprocess
from rich.console import Console

console = Console()


@dataclass
class EnvironmentVariable:
    """Environment variable specification."""

    name: str
    description: str


@dataclass
class AgentConfig:
    """Configuration for an agent loaded from YAML."""

    name: str
    description: str
    install_commands: List[str]
    fallback_install_commands: List[str]
    check_command: str
    launch_command: str
    default_args: List[str]
    dependencies: List[str]
    required_env_vars: List[EnvironmentVariable]
    recommended_env_vars: List[EnvironmentVariable]

    @classmethod
    def from_yaml_dict(cls, data: Dict[str, Any]) -> "AgentConfig":
        """Create AgentConfig from parsed YAML data."""
        install_data = data.get("install", {})
        launch_data = data.get("launch", {})
        env_data = data.get("environment", {})

        # Parse environment variables
        required_env_vars = []
        for env_var in env_data.get("required", []):
            required_env_vars.append(
                EnvironmentVariable(
                    name=env_var["name"], description=env_var["description"]
                )
            )

        recommended_env_vars = []
        for env_var in env_data.get("recommended", []):
            recommended_env_vars.append(
                EnvironmentVariable(
                    name=env_var["name"], description=env_var["description"]
                )
            )

        return cls(
            name=data["name"],
            description=data["description"],
            install_commands=install_data.get("commands", []),
            fallback_install_commands=install_data.get("fallback_commands", []),
            check_command=install_data.get("check_command", ""),
            launch_command=launch_data.get("command", ""),
            default_args=launch_data.get("default_args", []),
            dependencies=data.get("dependencies", []),
            required_env_vars=required_env_vars,
            recommended_env_vars=recommended_env_vars,
        )


def load_agent_config(
    agent_name: str, custom_path: Optional[Path] = None
) -> Optional[AgentConfig]:
    """Load agent configuration from YAML file.

    Args:
        agent_name: Name of the agent
        custom_path: Optional path to custom agent YAML file

    Returns:
        AgentConfig if found, None otherwise
    """
    if custom_path and custom_path.exists():
        yaml_path = custom_path
    else:
        # Look for built-in agent config
        agents_dir = Path(__file__).parent.parent / "agents"
        yaml_path = agents_dir / f"{agent_name}.yaml"

        if not yaml_path.exists():
            console.print(f"[red]✗ Agent configuration not found: {yaml_path}[/red]")
            return None

    try:
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)

        # Validate required fields
        required_fields = ["name", "description", "launch"]
        for field in required_fields:
            if field not in data:
                console.print(
                    f"[red]✗ Missing required field '{field}' in {yaml_path}[/red]"
                )
                return None

        return AgentConfig.from_yaml_dict(data)

    except yaml.YAMLError as e:
        console.print(f"[red]✗ Error parsing YAML file {yaml_path}: {e}[/red]")
        return None
    except Exception as e:
        console.print(f"[red]✗ Error loading agent config {yaml_path}: {e}[/red]")
        return None


def list_built_in_agents() -> List[str]:
    """List all built-in agent names."""
    agents_dir = Path(__file__).parent.parent / "agents"
    if not agents_dir.exists():
        return []

    agent_files = agents_dir.glob("*.yaml")
    return [f.stem for f in agent_files]


def validate_agent_config(config: AgentConfig) -> List[str]:
    """Validate an agent configuration and return list of issues."""
    issues = []

    if not config.name:
        issues.append("Agent name is required")

    if not config.description:
        issues.append("Agent description is required")

    if not config.launch_command:
        issues.append("Launch command is required")

    # Check if launch command is valid format
    if config.launch_command and not config.launch_command.strip():
        issues.append("Launch command cannot be empty")

    return issues


def is_agent_installed(config: AgentConfig) -> bool:
    """Check if an agent is installed using its check command."""
    if not config.check_command:
        # If no check command, assume it's installed (trust the user)
        return True

    try:
        # First try the check command directly
        result = subprocess.run(
            config.check_command.split(), capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        # Try with uv run prefix
        uv_command = ["uv", "run"] + config.check_command.split()
        result = subprocess.run(uv_command, capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install_agent(config: AgentConfig) -> bool:
    """Install an agent using its install commands.

    Returns:
        True if installation successful, False otherwise
    """
    if is_agent_installed(config):
        console.print(f"[green]✓ {config.name} is already installed[/green]")
        return True

    console.print(f"[yellow]Installing {config.name}...[/yellow]")

    # Try main install commands first
    for command in config.install_commands:
        try:
            console.print(f"[blue]Running: {command}[/blue]")
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes
            )

            if result.returncode == 0:
                console.print(f"[green]✓ Successfully installed {config.name}[/green]")
                return True
            else:
                console.print(f"[yellow]Command failed: {result.stderr}[/yellow]")

        except subprocess.TimeoutExpired:
            console.print(f"[yellow]Command timed out: {command}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Command error: {e}[/yellow]")

    # Try fallback commands if main commands failed
    if config.fallback_install_commands:
        console.print("[blue]Trying fallback installation methods...[/blue]")
        for command in config.fallback_install_commands:
            try:
                console.print(f"[blue]Running: {command}[/blue]")
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True, timeout=300
                )

                if result.returncode == 0:
                    console.print(
                        f"[green]✓ Successfully installed {config.name} with fallback method[/green]"
                    )
                    return True
                else:
                    console.print(
                        f"[yellow]Fallback command failed: {result.stderr}[/yellow]"
                    )

            except subprocess.TimeoutExpired:
                console.print(f"[yellow]Fallback command timed out: {command}[/yellow]")
            except Exception as e:
                console.print(f"[yellow]Fallback command error: {e}[/yellow]")

    console.print(f"[red]✗ Failed to install {config.name}[/red]")
    return False


def generate_launch_command(
    config: AgentConfig, workspace_config: Dict[str, Any]
) -> str:
    """Generate the launch command for an agent based on its config and workspace settings.

    Args:
        config: Agent configuration from YAML
        workspace_config: Workspace-specific settings

    Returns:
        Complete command string to launch the agent
    """
    command_parts = config.launch_command.split()

    # Add default arguments from agent config
    command_parts.extend(config.default_args)

    # Add workspace-specific configuration
    agent_settings = workspace_config.get("agent_config", {})

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


def check_environment_variables(config: AgentConfig) -> tuple[List[str], List[str]]:
    """Check environment variables for an agent.

    Returns:
        Tuple of (missing_required, missing_recommended)
    """
    import os

    missing_required = []
    missing_recommended = []

    for env_var in config.required_env_vars:
        if not os.getenv(env_var.name):
            missing_required.append(env_var.name)

    for env_var in config.recommended_env_vars:
        if not os.getenv(env_var.name):
            missing_recommended.append(env_var.name)

    return missing_required, missing_recommended


def report_environment_status(config: AgentConfig) -> None:
    """Report on environment variable status for an agent."""
    missing_required, missing_recommended = check_environment_variables(config)

    if not missing_required and not missing_recommended:
        console.print(
            f"[green]✓ All environment variables configured for {config.name}[/green]"
        )
        return

    if missing_required:
        console.print(
            f"[red]✗ Missing required environment variables for {config.name}:[/red]"
        )
        for env_var in config.required_env_vars:
            if env_var.name in missing_required:
                console.print(f"  [red]  {env_var.name}: {env_var.description}[/red]")

    if missing_recommended:
        console.print(
            f"[yellow]⚠ Missing recommended environment variables for {config.name}:[/yellow]"
        )
        for env_var in config.recommended_env_vars:
            if env_var.name in missing_recommended:
                console.print(
                    f"  [yellow]  {env_var.name}: {env_var.description}[/yellow]"
                )


def get_environment_setup_commands(config: AgentConfig) -> List[str]:
    """Get commands to set up environment variables for an agent.

    Returns:
        List of export commands for missing environment variables
    """
    missing_required, missing_recommended = check_environment_variables(config)
    commands = []

    all_env_vars = config.required_env_vars + config.recommended_env_vars
    missing_all = missing_required + missing_recommended

    for env_var in all_env_vars:
        if env_var.name in missing_all:
            commands.append(
                f"export {env_var.name}='your-{env_var.name.lower().replace('_', '-')}-here'"
            )

    return commands
