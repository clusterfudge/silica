"""Destroy command for silica."""

import subprocess
import shutil
import cyclopts
from typing import Annotated
from rich.console import Console
from rich.prompt import Confirm

from silica.remote.config import get_silica_dir, find_git_root
from silica.remote.utils import piku as piku_utils
from silica.remote.utils.antennae_client import get_antennae_client
from silica.remote.config.multi_workspace import is_local_workspace_for_cleanup

console = Console()


def destroy(
    force: Annotated[
        bool, cyclopts.Parameter(help="Force destruction without confirmation")
    ] = False,
    workspace: Annotated[
        str,
        cyclopts.Parameter(name=["--workspace", "-w"], help="Name for the workspace"),
    ] = "agent",
    all: Annotated[
        bool,
        cyclopts.Parameter(help="Destroy all workspaces and clean up all local files"),
    ] = False,
):
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
        from silica.remote.config.multi_workspace import (
            load_project_config,
            list_workspaces,
        )

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
                    console.print(f"[bold]Destroying workspace '{ws_name}'...[/bold]")

                    # Check if this is a local workspace
                    is_local = is_local_workspace_for_cleanup(silica_dir, ws_name)

                    # Try to destroy via HTTP first (while server is still running)
                    try:
                        client = get_antennae_client(silica_dir, ws_name)
                        success, response = client.destroy()

                        if success:
                            console.print(
                                f"[green]Destroyed workspace '{ws_name}' via HTTP[/green]"
                            )
                        else:
                            console.print(
                                f"[yellow]HTTP destroy failed for '{ws_name}': {response.get('error', 'Unknown error')}[/yellow]"
                            )

                    except Exception as e:
                        console.print(
                            f"[yellow]Could not destroy via HTTP for '{ws_name}': {e}[/yellow]"
                        )

                    # For local workspaces, stop the antennae tmux session after HTTP destroy
                    if is_local:
                        try:
                            from silica.remote.config.multi_workspace import (
                                get_workspace_config,
                            )

                            workspace_config = get_workspace_config(silica_dir, ws_name)
                            app_name = workspace_config.get("app_name", ws_name)

                            console.print(
                                f"[bold]Stopping antennae server for '{ws_name}' (session '{app_name}')...[/bold]"
                            )

                            check_result = subprocess.run(
                                ["tmux", "has-session", "-t", app_name],
                                capture_output=True,
                                check=False,
                            )

                            if check_result.returncode == 0:
                                kill_result = subprocess.run(
                                    ["tmux", "kill-session", "-t", app_name],
                                    capture_output=True,
                                    check=False,
                                )

                                if kill_result.returncode == 0:
                                    console.print(
                                        f"[green]Stopped antennae server for '{ws_name}'[/green]"
                                    )

                        except Exception as e:
                            console.print(
                                f"[yellow]Warning: Could not stop antennae server for '{ws_name}': {e}[/yellow]"
                            )

                    # For remote workspaces, also destroy the piku application
                    if not is_local:
                        try:
                            force_flag = "--force" if force else ""
                            piku_utils.run_piku_in_silica(
                                f"destroy {force_flag}", workspace_name=ws_name
                            )
                            console.print(
                                f"[green]Destroyed piku app for '{ws_name}'[/green]"
                            )
                        except Exception as e:
                            console.print(
                                f"[yellow]Warning: Could not destroy piku app for '{ws_name}': {e}[/yellow]"
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
    console.print(f"[bold]Destroying workspace '{workspace}'...[/bold]")

    # Gather ALL confirmations upfront before taking any destructive actions
    confirmations = {}

    # Main confirmation for workspace destruction
    if force:
        confirmations["destroy_workspace"] = True
    else:
        confirmation_message = (
            f"Are you sure you want to destroy workspace '{workspace}'?"
        )
        confirmations["destroy_workspace"] = Confirm.ask(confirmation_message)

    if not confirmations["destroy_workspace"]:
        console.print("[yellow]Aborted.[/yellow]")
        return

    # Only offer to clean up local files if this is the last workspace
    if confirmations["destroy_workspace"]:
        from silica.remote.config.multi_workspace import load_project_config

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
    try:
        # Check if this is a local workspace
        is_local = is_local_workspace_for_cleanup(silica_dir, workspace)

        # First, try to destroy via HTTP while the server is still running
        console.print("[bold]Destroying workspace via antennae...[/bold]")

        try:
            client = get_antennae_client(silica_dir, workspace)
            success, response = client.destroy()

            if success:
                console.print(
                    f"[green]Workspace '{workspace}' destroyed successfully via HTTP[/green]"
                )
            else:
                console.print(
                    f"[yellow]HTTP destroy failed: {response.get('error', 'Unknown error')}[/yellow]"
                )
                console.print("[yellow]Continuing with cleanup...[/yellow]")

        except Exception as e:
            console.print(f"[yellow]Could not destroy via HTTP: {e}[/yellow]")
            console.print("[yellow]Continuing with cleanup...[/yellow]")

        # For local workspaces, stop the antennae tmux session after HTTP destroy
        if is_local:
            try:
                # Get app name for tmux session name
                from silica.remote.config.multi_workspace import get_workspace_config

                workspace_config = get_workspace_config(silica_dir, workspace)
                app_name = workspace_config.get("app_name", workspace)

                console.print(
                    f"[bold]Stopping local antennae server (tmux session '{app_name}')...[/bold]"
                )

                # Check if tmux session exists
                check_result = subprocess.run(
                    ["tmux", "has-session", "-t", app_name],
                    capture_output=True,
                    check=False,
                )

                if check_result.returncode == 0:
                    # Kill the tmux session
                    kill_result = subprocess.run(
                        ["tmux", "kill-session", "-t", app_name],
                        capture_output=True,
                        check=False,
                    )

                    if kill_result.returncode == 0:
                        console.print(
                            f"[green]Stopped antennae server session '{app_name}'[/green]"
                        )
                    else:
                        console.print(
                            f"[yellow]Warning: Could not stop tmux session '{app_name}'[/yellow]"
                        )
                else:
                    console.print(
                        f"[yellow]Tmux session '{app_name}' not found (may already be stopped)[/yellow]"
                    )

            except Exception as e:
                console.print(
                    f"[yellow]Warning: Could not stop antennae server: {e}[/yellow]"
                )

        # For remote workspaces, also destroy the piku application
        if not is_local:
            try:
                console.print("[bold]Destroying piku application...[/bold]")
                force_flag = "--force" if force else ""
                piku_utils.run_piku_in_silica(
                    f"destroy {force_flag}", workspace_name=workspace
                )
                console.print("[green]Piku application destroyed successfully[/green]")
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Could not destroy piku application: {e}[/yellow]"
                )

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

        console.print(
            f"[green bold]Successfully destroyed workspace '{workspace}'![/green bold]"
        )

    except subprocess.CalledProcessError as e:
        error_output = e.stderr.decode() if e.stderr else str(e)
        console.print(f"[red]Error destroying workspace: {error_output}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")

    # Update configuration file to remove the workspace
    try:
        from silica.remote.config.multi_workspace import load_project_config

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
