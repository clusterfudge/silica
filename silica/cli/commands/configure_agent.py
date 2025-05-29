"""Advanced agent configuration command for silica."""

import click
from rich.console import Console
from rich.prompt import Prompt, Confirm

from silica.config import find_git_root, get_silica_dir
from silica.utils.yaml_agents import (
    get_supported_agents,
    update_workspace_with_agent,
    generate_agent_runner_script,
)
from silica.utils.agent_yaml import load_agent_config
from silica.config.multi_workspace import get_workspace_config, set_workspace_config

console = Console()


@click.command()
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
        agent_details = load_agent_config(agent_type)
        if not agent_details:
            console.print(f"[red]Error: Unknown agent type: {agent_type}[/red]")
            return

        console.print(
            f"[bold]Configuring {agent_type} for workspace '{workspace}'[/bold]"
        )
        console.print(f"Description: {agent_details.description}")
        console.print(f"Default command: {agent_details.launch_command}")
        console.print(f"Default args: {agent_details.default_args}")

        # Interactive configuration
        custom_config = {"flags": [], "args": {}}

        # Ask about additional flags
        if Confirm.ask("Add custom flags?", default=False):
            while True:
                flag = Prompt.ask("Enter flag name (without --)", default="")
                if not flag:
                    break
                custom_config["flags"].append(flag)
                if not Confirm.ask("Add another flag?", default=False):
                    break

        # Ask about custom arguments
        if Confirm.ask("Add custom arguments?", default=False):
            while True:
                arg_name = Prompt.ask("Enter argument name (without --)", default="")
                if not arg_name:
                    break
                arg_value = Prompt.ask(
                    f"Enter value for --{arg_name} (or 'true' for flag-only)",
                    default="true",
                )

                if arg_value.lower() == "true":
                    custom_config["args"][arg_name] = True
                elif arg_value.lower() == "false":
                    custom_config["args"][arg_name] = False
                else:
                    custom_config["args"][arg_name] = arg_value

                if not Confirm.ask("Add another argument?", default=False):
                    break

        # Update configuration with custom settings
        updated_config = update_workspace_with_agent(
            current_config, agent_type, custom_config
        )

        # Save updated configuration
        set_workspace_config(silica_dir, workspace, updated_config)

        # Regenerate agent runner script
        script_content = generate_agent_runner_script(workspace, updated_config)

        # Write the new script to the agent-repo
        agent_repo_path = silica_dir / "agent-repo"
        if agent_repo_path.exists():
            script_path = agent_repo_path / "AGENT_runner.py"
            with open(script_path, "w") as f:
                f.write(script_content)

            # Set executable permissions
            script_path.chmod(script_path.stat().st_mode | 0o755)

            console.print(
                f"[green]Successfully configured workspace '{workspace}' with agent '{agent_type}'[/green]"
            )

            # Show final configuration
            console.print("\n[bold]Final Configuration:[/bold]")
            if custom_config["flags"]:
                console.print(
                    f"Custom flags: [magenta]{custom_config['flags']}[/magenta]"
                )
            if custom_config["args"]:
                console.print(
                    f"Custom arguments: [magenta]{custom_config['args']}[/magenta]"
                )

            console.print(
                f"\n[yellow]Don't forget to sync your changes: silica sync -w {workspace}[/yellow]"
            )
        else:
            console.print("[red]Error: Agent repository not found.[/red]")

    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
