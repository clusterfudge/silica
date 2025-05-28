"""Agent management commands for silica."""

import click
from rich.console import Console
from rich.table import Table

from silica.config import find_git_root, get_silica_dir
from silica.utils.agents import (
    get_supported_agents,
    get_agent_config,
    update_workspace_with_agent,
    generate_agent_script,
)
from silica.utils.installers.manager import installer
from silica.config.multi_workspace import (
    get_workspace_config,
    set_workspace_config,
    list_workspaces,
)

console = Console()


@click.group()
def agents():
    """Manage agent types and configurations."""


@agents.command("list")
def list_agents():
    """List all supported agent types."""
    console.print("[bold]Supported Agent Types:[/bold]")

    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Name", style="cyan")
    table.add_column("Command", style="green")
    table.add_column("Description", style="white")
    table.add_column("Default Args", style="magenta")
    table.add_column("Installed", style="green")
    table.add_column("Dependencies", style="yellow")

    for agent_name in get_supported_agents():
        agent_config = get_agent_config(agent_name)
        if agent_config:
            deps = ", ".join(agent_config.required_dependencies)

            # Format default arguments
            default_flags = agent_config.default_args.get("flags", [])
            default_args = agent_config.default_args.get("args", {})

            defaults_str = ""
            if default_flags:
                defaults_str += " ".join(default_flags)
            if default_args:
                args_formatted = " ".join(
                    [f"--{k} {v}" for k, v in default_args.items()]
                )
                if defaults_str:
                    defaults_str += " " + args_formatted
                else:
                    defaults_str = args_formatted

            if not defaults_str:
                defaults_str = "[dim]none[/dim]"

            # Check installation status
            is_installed = installer.is_agent_installed(agent_name)
            install_status = "✓" if is_installed else "✗"
            install_style = "green" if is_installed else "red"

            table.add_row(
                agent_config.name,
                agent_config.command,
                agent_config.description,
                defaults_str,
                f"[{install_style}]{install_status}[/{install_style}]",
                deps,
            )

    console.print(table)


@agents.command("set")
@click.option(
    "-w",
    "--workspace",
    help="Workspace name (default: current default workspace)",
    default=None,
)
@click.argument(
    "agent_type", type=click.Choice(get_supported_agents(), case_sensitive=False)
)
def set_agent(workspace, agent_type):
    """Set the agent type for a workspace."""
    try:
        # Check if agent is installed
        if not installer.is_agent_installed(agent_type):
            console.print(f"[yellow]Warning: {agent_type} is not installed[/yellow]")
            from rich.prompt import Confirm

            if Confirm.ask(
                f"Would you like to install {agent_type} now?", default=True
            ):
                console.print(f"[blue]Installing {agent_type}...[/blue]")
                if installer.install_agent(agent_type):
                    console.print(
                        f"[green]✓ Successfully installed {agent_type}[/green]"
                    )
                else:
                    console.print(f"[red]✗ Failed to install {agent_type}[/red]")
                    install_cmd = installer.get_install_command(agent_type)
                    if install_cmd:
                        console.print(
                            f"[blue]Manual installation: {install_cmd}[/blue]"
                        )
                    if not Confirm.ask(
                        "Continue with agent configuration anyway?", default=False
                    ):
                        return
            else:
                console.print(
                    f"[yellow]Continuing without installing {agent_type}[/yellow]"
                )

        # Find git root and silica directory
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        silica_dir = get_silica_dir(git_root)
        if not silica_dir:
            console.print("[red]Error: No silica environment found.[/red]")
            return

        # Get current workspace configuration
        current_config = get_workspace_config(silica_dir, workspace)

        # Update with new agent settings
        updated_config = update_workspace_with_agent(current_config, agent_type)

        # Get actual workspace name (in case None was passed)
        if workspace is None:
            from silica.config.multi_workspace import get_default_workspace

            workspace = get_default_workspace(silica_dir)

        # Save updated configuration
        set_workspace_config(silica_dir, workspace, updated_config)

        # Regenerate AGENT.sh script
        script_content = generate_agent_script(updated_config)

        # Write the new script to the agent-repo
        agent_repo_path = silica_dir / "agent-repo"
        if agent_repo_path.exists():
            script_path = agent_repo_path / "AGENT.sh"
            with open(script_path, "w") as f:
                f.write(script_content)

            # Set executable permissions
            script_path.chmod(script_path.stat().st_mode | 0o755)

            console.print(
                f"[green]Successfully updated workspace '{workspace}' to use agent '{agent_type}'[/green]"
            )
            console.print(
                f"[yellow]Don't forget to sync your changes: silica sync -w {workspace}[/yellow]"
            )
        else:
            console.print("[red]Error: Agent repository not found.[/red]")

    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")


@agents.command("show")
@click.option(
    "-w",
    "--workspace",
    help="Workspace name (default: current default workspace)",
    default=None,
)
def show_agent(workspace):
    """Show the current agent configuration for a workspace."""
    try:
        # Find git root and silica directory
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        silica_dir = get_silica_dir(git_root)
        if not silica_dir:
            console.print("[red]Error: No silica environment found.[/red]")
            return

        # Get workspace configuration
        config = get_workspace_config(silica_dir, workspace)

        # Get actual workspace name (in case None was passed)
        if workspace is None:
            from silica.config.multi_workspace import get_default_workspace

            workspace = get_default_workspace(silica_dir)

        # Show current agent configuration
        agent_type = config.get("agent_type", "hdev")
        agent_config = config.get("agent_config", {})

        console.print(f"[bold]Agent Configuration for Workspace '{workspace}':[/bold]")
        console.print(f"Agent Type: [cyan]{agent_type}[/cyan]")

        # Show agent details
        agent_details = get_agent_config(agent_type)
        if agent_details:
            console.print(f"Description: [white]{agent_details.description}[/white]")
            console.print(f"Command: [green]{agent_details.command}[/green]")
            console.print(
                f"Dependencies: [yellow]{', '.join(agent_details.required_dependencies)}[/yellow]"
            )

            # Show default configuration from agent definition
            default_flags = agent_details.default_args.get("flags", [])
            default_args = agent_details.default_args.get("args", {})
            if default_flags or default_args:
                console.print("\n[bold]Default Agent Configuration:[/bold]")
                if default_flags:
                    console.print(f"Default flags: [blue]{default_flags}[/blue]")
                if default_args:
                    console.print(f"Default arguments: [blue]{default_args}[/blue]")

        # Show custom configuration
        if agent_config:
            console.print("\n[bold]Workspace Custom Configuration:[/bold]")
            if "flags" in agent_config:
                console.print(
                    f"Custom flags: [magenta]{agent_config['flags']}[/magenta]"
                )
            if "args" in agent_config:
                console.print(
                    f"Custom arguments: [magenta]{agent_config['args']}[/magenta]"
                )

        # Show the complete generated command
        from silica.utils.agents import generate_agent_command

        try:
            full_command = generate_agent_command(agent_type, config)
            console.print(
                f"\n[bold]Generated Command:[/bold] [cyan]{full_command}[/cyan]"
            )
        except Exception as e:
            console.print(f"\n[yellow]Could not generate command: {e}[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@agents.command("status")
def status():
    """Show agent configuration for all workspaces."""
    try:
        # Find git root and silica directory
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        silica_dir = get_silica_dir(git_root)
        if not silica_dir:
            console.print("[red]Error: No silica environment found.[/red]")
            return

        # Get all workspaces
        workspaces = list_workspaces(silica_dir)

        if not workspaces:
            console.print("[yellow]No workspaces found.[/yellow]")
            return

        console.print("[bold]Agent Status for All Workspaces:[/bold]")

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("Workspace", style="cyan")
        table.add_column("Default", style="green")
        table.add_column("Agent Type", style="magenta")
        table.add_column("Description", style="white")

        for workspace in workspaces:
            name = workspace["name"]
            is_default = "✓" if workspace["is_default"] else ""
            config = workspace["config"]

            agent_type = config.get("agent_type", "hdev")
            agent_details = get_agent_config(agent_type)
            description = (
                agent_details.description if agent_details else "Unknown agent"
            )

            table.add_row(name, is_default, agent_type, description)

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@agents.command("configure")
@click.option(
    "-w",
    "--workspace",
    help="Workspace name (default: current default workspace)",
    default=None,
)
@click.argument(
    "agent_type", type=click.Choice(get_supported_agents(), case_sensitive=False)
)
def configure_agent(workspace, agent_type):
    """Interactively configure an agent for a workspace with custom settings."""
    try:
        # Find git root and silica directory
        git_root = find_git_root()
        if not git_root:
            console.print("[red]Error: Not in a git repository.[/red]")
            return

        silica_dir = get_silica_dir(git_root)
        if not silica_dir:
            console.print("[red]Error: No silica environment found.[/red]")
            return

        # Get current workspace configuration
        current_config = get_workspace_config(silica_dir, workspace)

        # Get actual workspace name (in case None was passed)
        if workspace is None:
            from silica.config.multi_workspace import get_default_workspace

            workspace = get_default_workspace(silica_dir)

        # Get agent details for configuration
        agent_details = get_agent_config(agent_type)
        if not agent_details:
            console.print(f"[red]Error: Unknown agent type: {agent_type}[/red]")
            return

        console.print(
            f"[bold]Configuring {agent_type} for workspace '{workspace}'[/bold]"
        )
        console.print(f"Description: {agent_details.description}")
        console.print(f"Default command: {agent_details.command}")
        console.print(f"Default flags: {agent_details.default_args.get('flags', [])}")
        console.print(f"Default args: {agent_details.default_args.get('args', {})}")

        # Interactive configuration for custom settings
        from rich.prompt import Confirm, Prompt

        custom_config = {"flags": [], "args": {}}

        if Confirm.ask(
            "\nWould you like to add custom flags beyond the defaults?", default=False
        ):
            while True:
                flag = Prompt.ask("Enter custom flag (without --)", default="")
                if not flag:
                    break
                custom_config["flags"].append(flag)
                if not Confirm.ask("Add another flag?", default=False):
                    break

        if Confirm.ask(
            "Would you like to add custom arguments beyond the defaults?", default=False
        ):
            while True:
                arg_name = Prompt.ask("Enter argument name (without --)", default="")
                if not arg_name:
                    break
                arg_value = Prompt.ask(f"Enter value for --{arg_name}")
                custom_config["args"][arg_name] = arg_value
                if not Confirm.ask("Add another argument?", default=False):
                    break

        # Update configuration with agent type and custom settings
        updated_config = update_workspace_with_agent(
            current_config, agent_type, custom_config
        )

        # Save updated configuration
        set_workspace_config(silica_dir, workspace, updated_config)

        # Regenerate AGENT.sh script
        script_content = generate_agent_script(updated_config)

        # Write the new script to the agent-repo
        agent_repo_path = silica_dir / "agent-repo"
        if agent_repo_path.exists():
            script_path = agent_repo_path / "AGENT.sh"
            with open(script_path, "w") as f:
                f.write(script_content)

            # Set executable permissions
            script_path.chmod(script_path.stat().st_mode | 0o755)

            console.print(
                f"[green]Successfully configured workspace '{workspace}' with agent '{agent_type}'[/green]"
            )
            console.print(
                f"[yellow]Don't forget to sync your changes: silica sync -w {workspace}[/yellow]"
            )
        else:
            console.print("[red]Error: Agent repository not found.[/red]")

    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")


@agents.command("set-default")
@click.argument(
    "agent_type", type=click.Choice(get_supported_agents(), case_sensitive=False)
)
def set_default_agent(agent_type):
    """Set the global default agent type for new workspaces."""
    from silica.config import set_config_value

    set_config_value("default_agent", agent_type)
    console.print(f"[green]Global default agent set to: {agent_type}[/green]")
    console.print(
        "[dim]This will be used for new workspaces created without specifying -a/--agent[/dim]"
    )
    console.print(
        f"[dim]You can also use: silica config set-default-agent {agent_type}[/dim]"
    )


@agents.command("get-default")
def get_default_agent():
    """Show the current global default agent type."""
    from silica.config import get_config_value

    default_agent = get_config_value("default_agent", "hdev")
    console.print(f"[bold]Global default agent:[/bold] [cyan]{default_agent}[/cyan]")

    agent_details = get_agent_config(default_agent)
    if agent_details:
        console.print(f"Description: [white]{agent_details.description}[/white]")
        console.print(f"Command: [green]{agent_details.command}[/green]")


@agents.command("install")
@click.argument(
    "agent_type", type=click.Choice(get_supported_agents(), case_sensitive=False)
)
def install_agent(agent_type):
    """Install a specific agent."""
    console.print(f"[bold]Installing {agent_type}...[/bold]")

    if installer.is_agent_installed(agent_type):
        console.print(f"[green]✓ {agent_type} is already installed[/green]")
        return

    success = installer.install_agent(agent_type)
    if success:
        console.print(f"[green]✓ Successfully installed {agent_type}[/green]")
    else:
        console.print(f"[red]✗ Failed to install {agent_type}[/red]")
        install_cmd = installer.get_install_command(agent_type)
        if install_cmd:
            console.print(f"[blue]Manual installation: {install_cmd}[/blue]")


@agents.command("check-install")
def check_install():
    """Check installation status of all agents."""
    console.print("[bold]Agent Installation Status:[/bold]")

    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Agent", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Install Command", style="yellow")

    status = installer.check_all_agents()
    for agent_type, is_installed in status.items():
        status_text = (
            "[green]✓ Installed[/green]"
            if is_installed
            else "[red]✗ Not Installed[/red]"
        )
        install_cmd = installer.get_install_command(agent_type) or "N/A"

        table.add_row(agent_type, status_text, install_cmd)

    console.print(table)


@agents.command("install-all")
def install_all():
    """Install all available agents."""
    from rich.prompt import Confirm

    console.print("[bold]Installing all available agents...[/bold]")

    if not Confirm.ask(
        "This will attempt to install all agents. Continue?", default=True
    ):
        console.print("[yellow]Installation cancelled.[/yellow]")
        return

    agent_types = get_supported_agents()
    results = installer.install_required_agents(agent_types)

    console.print("\n[bold]Installation Summary:[/bold]")
    for agent_type, success in results.items():
        status = "[green]✓ Success[/green]" if success else "[red]✗ Failed[/red]"
        console.print(f"  {agent_type}: {status}")
