"""Destroy command for silica."""

import subprocess
import shutil
import click
from rich.console import Console
from rich.prompt import Confirm

from silica.config import get_silica_dir, find_git_root
from silica.utils import piku as piku_utils
from silica.utils.piku import get_piku_connection, get_app_name

console = Console()


@click.command()
@click.option("--force", is_flag=True, help="Force destruction without confirmation")
@click.option(
    "-w",
    "--workspace",
    help="Name for the workspace (default: agent)",
    default="agent",
)
@click.option(
    "--all",
    is_flag=True,
    help="Destroy all workspaces and clean up all local files",
)
def destroy(force, workspace, all):
    """Destroy the agent environment.

    When used with --all, destroys all workspaces and cleans up all local files.
    Otherwise, destroys only the specified workspace.
    """
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    silica_dir = get_silica_dir()
    if not silica_dir or not (silica_dir / "config.yaml").exists():
        console.print(
            "[red]Error: No silica environment found in this repository.[/red]"
        )
        return

    # Handle --all flag to destroy all workspaces
    if all:
        from silica.config.multi_workspace import load_project_config, list_workspaces

        # Get all workspaces
        config = load_project_config(silica_dir)
        all_workspaces = list_workspaces(silica_dir)

        if not all_workspaces:
            console.print("[yellow]No workspaces found to destroy.[/yellow]")
            return

        # Get confirmation for destroying all workspaces
        workspace_names = [ws["name"] for ws in all_workspaces]
        confirmation_message = (
            "Are you sure you want to destroy ALL workspaces? This will remove:\n"
        )
        for name in workspace_names:
            confirmation_message += f"  - Workspace '{name}'\n"
        confirmation_message += "This action will clean up all remote and local files."

        if force or Confirm.ask(confirmation_message, default=False):
            console.print("[bold]Destroying all workspaces...[/bold]")

            # Destroy each workspace
            success_count = 0
            for ws in all_workspaces:
                ws_name = ws["name"]
                try:
                    # Get app name for this workspace
                    current_app_name = get_app_name(git_root, workspace_name=ws_name)

                    console.print(f"[bold]Destroying {current_app_name}...[/bold]")

                    # Check for tmux session
                    has_tmux_session = False
                    try:
                        check_cmd = f"tmux has-session -t {current_app_name} 2>/dev/null || echo 'no_session'"
                        check_result = piku_utils.run_piku_in_silica(
                            check_cmd,
                            workspace_name=ws_name,
                            use_shell_pipe=True,
                            capture_output=True,
                        )
                        has_tmux_session = "no_session" not in check_result.stdout
                    except Exception:
                        has_tmux_session = False

                    # Terminate tmux if exists
                    if has_tmux_session:
                        console.print(
                            f"[bold]Terminating tmux session for {current_app_name}...[/bold]"
                        )
                        try:
                            kill_cmd = f"tmux kill-session -t {current_app_name}"
                            piku_utils.run_piku_in_silica(
                                kill_cmd, workspace_name=ws_name, use_shell_pipe=True
                            )
                            console.print(
                                f"[green]Terminated tmux session for {current_app_name}.[/green]"
                            )
                        except Exception as e:
                            console.print(
                                f"[yellow]Warning: Could not terminate tmux session for {ws_name}: {e}[/yellow]"
                            )

                    # Destroy the piku application
                    force_flag = "--force" if force else ""
                    piku_utils.run_piku_in_silica(
                        f"destroy {force_flag}", workspace_name=ws_name
                    )

                    console.print(
                        f"[green]Successfully destroyed {current_app_name}![/green]"
                    )
                    success_count += 1

                except Exception as e:
                    console.print(
                        f"[red]Error destroying workspace {ws_name}: {e}[/red]"
                    )

            # Remove all local files
            try:
                console.print("[bold]Cleaning up all local silica files...[/bold]")
                # Clean the contents but keep the directory
                for item in silica_dir.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                console.print(
                    "[green]All local silica environment files removed.[/green]"
                )
            except Exception as e:
                console.print(f"[red]Error removing local files: {e}[/red]")

            console.print(
                f"[green bold]Successfully destroyed {success_count}/{len(all_workspaces)} workspaces![/green bold]"
            )
            return
        else:
            console.print("[yellow]Destruction of all workspaces aborted.[/yellow]")
            return

    # Regular single workspace destruction
    # Use our utility functions to get workspace name, app name, etc.
    app_name = get_app_name(git_root)
    piku_connection = get_piku_connection(git_root)

    if not workspace or not piku_connection or not app_name:
        console.print("[red]Error: Invalid configuration.[/red]")
        return

    # Gather ALL confirmations upfront before taking any destructive actions
    confirmations = {}

    # Check if there's a tmux session for this app
    has_tmux_session = False
    try:
        check_cmd = f"tmux has-session -t {app_name} 2>/dev/null || echo 'no_session'"
        check_result = piku_utils.run_piku_in_silica(
            check_cmd,
            workspace_name=workspace,
            use_shell_pipe=True,
            capture_output=True,
        )
        has_tmux_session = "no_session" not in check_result.stdout
    except Exception:
        has_tmux_session = False  # Assume no session on error

    # Main confirmation for app destruction
    if force:
        confirmations["destroy_app"] = True
    else:
        confirmation_message = f"Are you sure you want to destroy {app_name}?"
        if has_tmux_session:
            confirmation_message += (
                f"\nThis will also terminate the tmux session for {app_name}."
            )

        confirmations["destroy_app"] = Confirm.ask(confirmation_message)

    if not confirmations["destroy_app"]:
        console.print("[yellow]Aborted.[/yellow]")
        return

    # Only offer to clean up local files if this is the last workspace
    if confirmations["destroy_app"]:
        from silica.config.multi_workspace import load_project_config

        config = load_project_config(silica_dir)
        remaining_workspaces = 0

        # Count existing workspaces excluding the one we're destroying
        if "workspaces" in config:
            workspaces_except_current = [
                ws for ws in config["workspaces"] if ws != workspace
            ]
            remaining_workspaces = len(workspaces_except_current)

        if remaining_workspaces == 0:
            # This is the last workspace, offer to clean up local files
            confirmations["remove_local_files"] = Confirm.ask(
                "This is the last workspace. Do you want to remove all local silica environment files?",
                default=True,
            )
        else:
            # Other workspaces exist, don't remove local files
            confirmations["remove_local_files"] = False

    # Now that we have all confirmations, proceed with destruction actions
    console.print(f"[bold]Destroying {app_name}...[/bold]")

    try:
        # First terminate tmux sessions if they exist and user confirmed
        if has_tmux_session and confirmations["destroy_app"]:
            console.print(f"[bold]Terminating tmux session for {app_name}...[/bold]")
            try:
                kill_cmd = f"tmux kill-session -t {app_name}"
                piku_utils.run_piku_in_silica(
                    kill_cmd, workspace_name=workspace, use_shell_pipe=True
                )
                console.print(f"[green]Terminated tmux session for {app_name}.[/green]")
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Could not terminate tmux session: {e}[/yellow]"
                )

        # Now destroy the piku application
        force_flag = "--force" if force else ""
        piku_utils.run_piku_in_silica(f"destroy {force_flag}", workspace_name=workspace)

        # Remove local .silica directory contents if confirmed (only if this is the last workspace)
        if confirmations["remove_local_files"]:
            # Just clean the contents but keep the directory
            for item in silica_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

            console.print("[green]Local silica environment files removed.[/green]")
        else:
            # Check if we need to remove the agent-repo remote for this workspace
            try:
                agent_repo_path = silica_dir / "agent-repo"
                if agent_repo_path.exists():
                    import git

                    agent_repo = git.Repo(agent_repo_path)

                    # Check if remote exists with the workspace name
                    remote_exists = any(
                        remote.name == workspace for remote in agent_repo.remotes
                    )

                    if remote_exists:
                        # Remove the remote
                        agent_repo.git.remote("remove", workspace)
                        console.print(
                            f"[green]Removed git remote '{workspace}' from agent repository.[/green]"
                        )
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Could not remove git remote: {e}[/yellow]"
                )

        console.print(f"[green bold]Successfully destroyed {app_name}![/green bold]")

    except subprocess.CalledProcessError as e:
        error_output = e.stderr.decode() if e.stderr else str(e)
        console.print(f"[red]Error destroying environment: {error_output}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")

    # Update configuration file to remove the workspace
    try:
        from silica.config.multi_workspace import load_project_config

        if (silica_dir / "config.yaml").exists():
            # Load existing config
            config = load_project_config(silica_dir)

            # Remove the workspace if it exists
            if "workspaces" in config and workspace in config["workspaces"]:
                del config["workspaces"][workspace]

                # Count remaining workspaces after removing this one
                remaining_workspaces = len(config.get("workspaces", {}))

                if remaining_workspaces > 0:
                    console.print(
                        f"[green]Removed workspace '{workspace}' from configuration. "
                        f"({remaining_workspaces} workspace{'s' if remaining_workspaces != 1 else ''} remaining)[/green]"
                    )
                else:
                    console.print(
                        f"[green]Removed workspace '{workspace}' from configuration. No workspaces remaining.[/green]"
                    )

                # If we removed the default workspace, set a new default
                if config.get("default_workspace") == workspace:
                    # Find another workspace to set as default, or use "agent" if none exist
                    if config["workspaces"]:
                        new_default = next(iter(config["workspaces"].keys()))
                        config["default_workspace"] = new_default
                        console.print(
                            f"[green]Set new default workspace to '{new_default}'.[/green]"
                        )
                    else:
                        config["default_workspace"] = "agent"
                        console.print(
                            "[yellow]No workspaces left. Default reset to 'agent'.[/yellow]"
                        )

                # Save the updated config
                import yaml

                with open(silica_dir / "config.yaml", "w") as f:
                    yaml.dump(config, f, default_flow_style=False)
            else:
                console.print(
                    f"[yellow]Note: Workspace '{workspace}' was not found in local configuration.[/yellow]"
                )
    except Exception as e:
        console.print(
            f"[yellow]Warning: Could not update local configuration file: {e}[/yellow]"
        )