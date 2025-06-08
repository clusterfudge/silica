"""Workspace Environment commands for silica.

This module provides commands for managing the workspace environment on remote deployments.
These commands are designed to be run within the deployed silica environment to handle
agent setup, execution, and environment management.
"""

import os
import sys
import subprocess
import json
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from silica.utils.yaml_agents import (
    get_agent_config,
    get_supported_agents,
)

console = Console()


def load_environment_variables():
    """Load environment variables from piku ENV file."""
    top_dir = Path.cwd()
    app_name = top_dir.name
    
    env_file = Path.home() / ".piku" / "envs" / app_name / "ENV"
    
    env_vars_loaded = 0
    if env_file.exists():
        console.print(f"[dim]Loading environment from {env_file}[/dim]")
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
                    env_vars_loaded += 1
        console.print(f"[green]✓ Loaded {env_vars_loaded} environment variables[/green]")
    else:
        console.print(f"[yellow]⚠ Environment file not found: {env_file}[/yellow]")
    
    return env_vars_loaded > 0


def sync_dependencies():
    """Synchronize UV dependencies."""
    console.print("[dim]Synchronizing dependencies with uv...[/dim]")
    try:
        result = subprocess.run(
            ["uv", "sync"],
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode == 0:
            console.print("[green]✓ Dependencies synchronized successfully[/green]")
            return True
        else:
            console.print(f"[yellow]⚠ uv sync warning: {result.stderr}[/yellow]")
            return False
    except subprocess.TimeoutExpired:
        console.print("[red]✗ uv sync timed out[/red]")
        return False
    except FileNotFoundError:
        console.print("[red]✗ uv not found - please install uv[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ uv sync error: {e}[/red]")
        return False


def is_agent_installed(agent_config: Dict[str, Any]) -> bool:
    """Check if agent is installed."""
    install_data = agent_config.get('install', {})
    check_command = install_data.get('check_command', '')
    
    if not check_command:
        return True
        
    # Try direct command first
    try:
        result = subprocess.run(
            check_command.split(),
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    # Try with uv run
    try:
        uv_command = ["uv", "run"] + check_command.split()
        result = subprocess.run(
            uv_command,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install_agent(agent_config: Dict[str, Any]) -> bool:
    """Install agent if needed."""
    if is_agent_installed(agent_config):
        console.print(f"[green]✓ {agent_config['name']} is already installed[/green]")
        return True
        
    console.print(f"[yellow]Installing {agent_config['name']}...[/yellow]")
    
    install_data = agent_config.get('install', {})
    
    # Try main install commands
    for command in install_data.get('commands', []):
        try:
            console.print(f"[dim]Running: {command}[/dim]")
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                console.print(f"[green]✓ Successfully installed {agent_config['name']}[/green]")
                return True
            else:
                console.print(f"[yellow]Command failed: {result.stderr}[/yellow]")
                
        except Exception as e:
            console.print(f"[yellow]Command error: {e}[/yellow]")
    
    # Try fallback commands
    for command in install_data.get('fallback_commands', []):
        try:
            console.print(f"[dim]Running fallback: {command}[/dim]")
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                console.print(f"[green]✓ Successfully installed {agent_config['name']} with fallback[/green]")
                return True
                
        except Exception as e:
            console.print(f"[yellow]Fallback error: {e}[/yellow]")
    
    console.print(f"[red]✗ Failed to install {agent_config['name']}[/red]")
    return False


def check_environment_variables(agent_config: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    """Check and report environment variable status."""
    env_data = agent_config.get('environment', {})
    missing_required = []
    missing_recommended = []
    
    # Check required environment variables
    for env_var in env_data.get('required', []):
        env_name = env_var['name']
        if not os.getenv(env_name):
            missing_required.append((env_name, env_var['description']))
    
    # Check recommended environment variables  
    for env_var in env_data.get('recommended', []):
        env_name = env_var['name']
        if not os.getenv(env_name):
            missing_recommended.append((env_name, env_var['description']))
    
    # Report status
    success = len(missing_required) == 0
    if success and len(missing_recommended) == 0:
        console.print(f"[green]✓ All environment variables configured for {agent_config['name']}[/green]")
    elif success:
        console.print(f"[yellow]⚠ Missing recommended environment variables for {agent_config['name']}[/yellow]")
    else:
        console.print(f"[red]✗ Missing required environment variables for {agent_config['name']}[/red]")
    
    return success, missing_required, missing_recommended


def get_workspace_config() -> Optional[Dict[str, Any]]:
    """Get workspace configuration from the current environment."""
    # In the deployed environment, we need to determine workspace config
    # This could come from environment variables set by piku, or from a config file
    
    # Try to get from environment variables first (set during deployment)
    workspace_name = os.getenv('SILICA_WORKSPACE_NAME', 'agent')
    agent_type = os.getenv('SILICA_AGENT_TYPE', 'hdev')
    
    # Build a basic workspace config
    workspace_config = {
        'agent_type': agent_type,
        'agent_config': {
            'flags': [],
            'args': {}
        }
    }
    
    # Try to load more detailed config from a local file if it exists
    config_file = Path.cwd() / 'workspace_config.json'
    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                file_config = json.load(f)
                workspace_config.update(file_config)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not load workspace config: {e}[/yellow]")
    
    return workspace_config


def setup_code_directory() -> bool:
    """Ensure code directory exists and is accessible."""
    code_dir = Path.cwd() / "code"
    
    if code_dir.exists() and code_dir.is_dir():
        console.print(f"[green]✓ Code directory found: {code_dir}[/green]")
        return True
    else:
        console.print(f"[yellow]⚠ Code directory not found: {code_dir}[/yellow]")
        console.print("[yellow]Code directory should be set up by the sync process[/yellow]")
        return False


def generate_launch_command(agent_config: Dict[str, Any], workspace_config: Dict[str, Any]) -> str:
    """Generate launch command for the agent."""
    launch_data = agent_config.get('launch', {})
    command_parts = launch_data.get('command', '').split()
    
    # Add default args
    command_parts.extend(launch_data.get('default_args', []))
    
    # Add workspace-specific args
    agent_settings = workspace_config.get("agent_config", {})
    command_parts.extend(agent_settings.get("flags", []))
    
    for key, value in agent_settings.get("args", {}).items():
        if value is True:
            command_parts.append(f"--{key}")
        elif value is not False and value is not None:
            command_parts.extend([f"--{key}", str(value)])
    
    return " ".join(command_parts)


@click.group()
def workspace_environment():
    """Manage workspace environment for deployed silica agents."""
    pass


# Add aliases
@click.group()
def workspace_environment_():
    """Manage workspace environment for deployed silica agents (alias)."""
    pass


@click.group()
def we():
    """Manage workspace environment for deployed silica agents (short alias)."""
    pass


@workspace_environment.command()
@workspace_environment_.command()
@we.command()
def setup():
    """Set up the workspace environment idempotently."""
    console.print(Panel.fit("[bold blue]Silica Workspace Environment Setup[/bold blue]", 
                          border_style="blue"))
    
    # Load environment
    load_environment_variables()
    
    # Sync dependencies
    if not sync_dependencies():
        console.print("[red]✗ Failed to sync dependencies[/red]")
        sys.exit(1)
    
    # Get workspace configuration
    workspace_config = get_workspace_config()
    if not workspace_config:
        console.print("[red]✗ Could not determine workspace configuration[/red]")
        sys.exit(1)
    
    agent_type = workspace_config.get('agent_type', 'hdev')
    console.print(f"[cyan]Agent type: {agent_type}[/cyan]")
    
    # Get agent configuration
    try:
        agent_config = get_agent_config(agent_type)
    except Exception as e:
        console.print(f"[red]✗ Could not load agent config for '{agent_type}': {e}[/red]")
        sys.exit(1)
    
    # Install agent
    if not install_agent(agent_config):
        console.print("[red]✗ Failed to install agent[/red]")
        sys.exit(1)
    
    # Check environment variables
    env_ok, missing_req, missing_rec = check_environment_variables(agent_config)
    if not env_ok:
        console.print("[red]✗ Required environment variables are missing:[/red]")
        for env_name, description in missing_req:
            console.print(f"    [red]{env_name}[/red]: {description}")
        sys.exit(1)
    
    if missing_rec:
        console.print("[yellow]⚠ Recommended environment variables are missing:[/yellow]")
        for env_name, description in missing_rec:
            console.print(f"    [yellow]{env_name}[/yellow]: {description}")
    
    # Check code directory
    setup_code_directory()
    
    console.print(Panel.fit("[bold green]✓ Workspace environment setup complete![/bold green]", 
                          border_style="green"))


@workspace_environment.command()
@workspace_environment_.command()  
@we.command()
def run():
    """Run the configured agent in the workspace environment."""
    console.print(Panel.fit("[bold blue]Starting Silica Agent[/bold blue]", 
                          border_style="blue"))
    
    # Load environment
    load_environment_variables()
    
    # Get workspace configuration
    workspace_config = get_workspace_config()
    if not workspace_config:
        console.print("[red]✗ Could not determine workspace configuration[/red]")
        sys.exit(1)
    
    agent_type = workspace_config.get('agent_type', 'hdev')
    
    # Get agent configuration
    try:
        agent_config = get_agent_config(agent_type)
    except Exception as e:
        console.print(f"[red]✗ Could not load agent config for '{agent_type}': {e}[/red]")
        sys.exit(1)
    
    # Change to code directory if it exists
    code_dir = Path.cwd() / "code"
    if code_dir.exists():
        os.chdir(code_dir)
        console.print(f"[green]Changed to code directory: {code_dir}[/green]")
    else:
        console.print(f"[yellow]Code directory not found, staying in: {Path.cwd()}[/yellow]")
    
    # Ensure agent is installed
    if not is_agent_installed(agent_config):
        console.print(f"[yellow]Agent {agent_config['name']} not installed, installing now...[/yellow]")
        if not install_agent(agent_config):
            console.print("[red]✗ Failed to install agent[/red]")
            sys.exit(1)
    
    # Generate and run launch command
    launch_command = generate_launch_command(agent_config, workspace_config)
    
    console.print(f"[cyan]Launch command: {launch_command}[/cyan]")
    console.print(f"[green]Starting {agent_config['name']} agent from {os.getcwd()} at {datetime.now()}[/green]")
    
    try:
        result = subprocess.run(launch_command, shell=True)
        console.print(f"[yellow]Agent exited with status {result.returncode} at {datetime.now()}[/yellow]")
        
    except KeyboardInterrupt:
        console.print("[yellow]Agent interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error running agent: {e}[/red]")
        sys.exit(1)
    
    console.print("[dim]Agent process has ended. Keeping tmux session alive.[/dim]")
    try:
        input("Press Enter to exit...")
    except (KeyboardInterrupt, EOFError):
        pass


@workspace_environment.command()
@workspace_environment_.command()
@we.command()
def status():
    """Check the status of the workspace environment."""
    console.print(Panel.fit("[bold blue]Workspace Environment Status[/bold blue]", 
                          border_style="blue"))
    
    # Create status table
    table = Table(title="Environment Status", show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan", no_wrap=True)
    table.add_column("Status", style="white")
    table.add_column("Details", style="dim")
    
    # Check current directory
    current_dir = Path.cwd()
    table.add_row("Working Directory", "✓", str(current_dir))
    
    # Check if we can load environment
    env_loaded = load_environment_variables()
    env_status = "✓ Loaded" if env_loaded else "✗ Not Found"
    table.add_row("Environment Variables", env_status, "From piku ENV file")
    
    # Check uv availability
    try:
        result = subprocess.run(["uv", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            uv_version = result.stdout.strip()
            table.add_row("UV Package Manager", "✓ Available", uv_version)
        else:
            table.add_row("UV Package Manager", "✗ Error", "Command failed")
    except FileNotFoundError:
        table.add_row("UV Package Manager", "✗ Not Found", "Please install uv")
    except Exception as e:
        table.add_row("UV Package Manager", "✗ Error", str(e))
    
    # Check workspace config
    workspace_config = get_workspace_config()
    if workspace_config:
        agent_type = workspace_config.get('agent_type', 'unknown')
        table.add_row("Workspace Config", "✓ Found", f"Agent type: {agent_type}")
        
        # Check agent config
        try:
            agent_config = get_agent_config(agent_type)
            table.add_row("Agent Config", "✓ Valid", agent_config['name'])
            
            # Check if agent is installed
            if is_agent_installed(agent_config):
                table.add_row("Agent Installation", "✓ Installed", agent_config['name'])
            else:
                table.add_row("Agent Installation", "✗ Not Installed", "Run setup to install")
            
            # Check environment variables
            env_ok, missing_req, missing_rec = check_environment_variables(agent_config)
            if env_ok and not missing_rec:
                table.add_row("Agent Environment", "✓ Complete", "All variables configured")
            elif env_ok:
                table.add_row("Agent Environment", "⚠ Partial", f"{len(missing_rec)} recommended missing")
            else:
                table.add_row("Agent Environment", "✗ Incomplete", f"{len(missing_req)} required missing")
                
        except Exception as e:
            table.add_row("Agent Config", "✗ Error", str(e))
    else:
        table.add_row("Workspace Config", "✗ Not Found", "Cannot determine configuration")
    
    # Check code directory
    code_dir = current_dir / "code"
    if code_dir.exists() and code_dir.is_dir():
        try:
            # Check if it's a git repo
            git_dir = code_dir / ".git"
            if git_dir.exists():
                # Get current branch
                result = subprocess.run(
                    ["git", "branch", "--show-current"], 
                    cwd=code_dir, 
                    capture_output=True, 
                    text=True, 
                    timeout=5
                )
                if result.returncode == 0:
                    branch = result.stdout.strip()
                    table.add_row("Code Directory", "✓ Git Repository", f"Branch: {branch}")
                else:
                    table.add_row("Code Directory", "✓ Git Repository", "Branch unknown")
            else:
                table.add_row("Code Directory", "✓ Directory", "Not a git repository")
        except Exception as e:
            table.add_row("Code Directory", "✓ Directory", f"Git status error: {e}")
    else:
        table.add_row("Code Directory", "✗ Not Found", "Should be synced separately")
    
    console.print(table)
    
    # Show next steps if there are issues
    console.print("\n[bold]Next Steps:[/bold]")
    if not env_loaded:
        console.print("• Environment variables not loaded - check piku configuration")
    
    workspace_config = get_workspace_config()
    if workspace_config:
        try:
            agent_config = get_agent_config(workspace_config.get('agent_type', 'hdev'))
            if not is_agent_installed(agent_config):
                console.print("• Run [cyan]silica we setup[/cyan] to install the agent")
            
            env_ok, missing_req, missing_rec = check_environment_variables(agent_config)
            if not env_ok:
                console.print("• Configure required environment variables through piku")
        except Exception:
            console.print("• Fix agent configuration issues")
    
    if not (code_dir.exists() and code_dir.is_dir()):
        console.print("• Sync code directory using [cyan]silica sync[/cyan]")
    
    console.print("• Run [cyan]silica we run[/cyan] to start the agent")