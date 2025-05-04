"""Commands for interacting with piku."""

import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
import subprocess

from silica.config import find_git_root, get_silica_dir
from silica.utils import piku as piku_utils
from silica.utils.piku import get_workspace_name, get_app_name

console = Console()


@click.group(name="piku")
def piku():
    """Interact with piku for the current agent environment."""


@piku.command(name="status")
def status():
    """Show the status of the agent environment."""
    try:
        workspace = get_workspace_name()
        app_name = get_app_name()
        result = piku_utils.run_piku_in_silica(
            f"status {app_name}", capture_output=True, workspace_name=workspace
        )
        console.print("[green]Application status:[/green]")
        for line in result.stdout.strip().split("\n"):
            console.print(f"  {line}")
    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr if e.stderr else str(e)}[/red]")


@piku.command(name="logs")
@click.option(
    "-n", "--lines", type=int, default=None, help="Number of log lines to display"
)
@click.option("-f", "--follow", is_flag=True, help="Follow the logs")
def logs(lines, follow):
    """Show logs from the agent environment."""
    try:
        workspace = get_workspace_name()
        app_name = get_app_name()

        logs_args = [app_name]
        if lines is not None:
            logs_args.append(str(lines))

        logs_cmd = f"logs {' '.join(logs_args)}"

        # For follow mode, we can't capture output
        capture_output = not follow

        piku_utils.run_piku_in_silica(
            logs_cmd, capture_output=capture_output, workspace_name=workspace
        )
    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr if e.stderr else str(e)}[/red]")


@piku.command(name="restart")
def restart():
    """Restart the agent environment."""
    try:
        workspace = get_workspace_name()
        app_name = get_app_name()
        piku_utils.run_piku_in_silica(f"restart {app_name}", workspace_name=workspace)
        console.print("[green]Agent environment restarted[/green]")
    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr if e.stderr else str(e)}[/red]")


@piku.command(name="deploy")
def deploy():
    """Deploy the agent environment."""
    try:
        git_root = find_git_root()
        if not git_root:
            raise ValueError("Not in a git repository")

        # Get agent configuration including workspace_name and branch
        workspace_name = get_workspace_name(git_root)

        # Get branch from config
        silica_dir = get_silica_dir(git_root)
        import yaml

        with open(silica_dir / "config.yaml", "r") as f:
            config = yaml.safe_load(f)

        branch = config.get("branch", "main")

        # Get the agent repository path
        repo_path = silica_dir / "agent-repo"

        console.print("Deploying agent environment...")

        # Add all changes
        import git

        repo = git.Repo(repo_path)
        repo.git.add(".")

        # Commit if there are changes
        if repo.is_dirty() or len(repo.untracked_files) > 0:
            repo.git.commit("-m", "Update agent environment")

        # Push to the git remote with the same name as workspace_name
        piku_utils.run_in_silica_dir(
            f"cd agent-repo && git push {workspace_name} {branch}", use_shell=True
        )

        console.print("[green]Agent environment deployed successfully[/green]")
    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr if e.stderr else str(e)}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")


@piku.command(name="sync")
def sync():
    """Sync the local repository to the remote code directory."""
    try:
        workspace = get_workspace_name()
        git_root = find_git_root()
        if not git_root:
            raise ValueError("Not in a git repository")

        # Get application name
        app_name = get_app_name()

        console.print("Syncing local repository to remote code directory...")

        # Create an rsync command to sync the local repo to the remote's code directory
        # Exclude the .silica and .git directories
        rsync_cmd = (
            f"rsync -av --delete --exclude='.silica' --exclude='.git' "
            f"{git_root}/ "
            f"/home/piku/app_dirs/{app_name}/code/"
        )

        # Run the rsync command using run_piku_in_silica
        piku_utils.run_piku_in_silica(
            rsync_cmd, use_shell_pipe=True, workspace_name=workspace
        )

        console.print("[green]Repository synced successfully[/green]")
    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr if e.stderr else str(e)}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")


@piku.command(name="sessions")
def sessions():
    """List active sessions in the agent environment."""
    try:
        workspace = get_workspace_name()

        # Use run_piku_in_silica to run the hdev sessions command
        result = piku_utils.run_piku_in_silica(
            "hdev sessions",
            use_shell_pipe=True,
            capture_output=True,
            workspace_name=workspace,
        )
        sessions_output = result.stdout.strip()

        # Skip if no sessions found
        if "No sessions found" in sessions_output:
            console.print("[yellow]No active sessions found[/yellow]")
            return

        # Process the output to build a table
        table = Table(title="Active Sessions")
        table.add_column("ID", style="cyan")
        table.add_column("Started", style="green")
        table.add_column("Working Directory", style="blue")

        # Parse the lines
        lines = sessions_output.split("\n")
        if len(lines) > 1:
            for line in lines[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 3:
                    session_id = parts[0]
                    started = parts[1]
                    workdir = " ".join(parts[2:])
                    table.add_row(session_id, started, workdir)

        console.print(table)
    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr if e.stderr else str(e)}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")


@piku.command(name="config")
def config():
    """Show the configuration for the agent environment."""
    try:
        workspace = get_workspace_name()
        app_name = get_app_name()

        # Get configuration using run_piku_in_silica
        result = piku_utils.run_piku_in_silica(
            f"config:get {app_name}", capture_output=True, workspace_name=workspace
        )

        # Parse the output into a dictionary
        config = {}
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                config[k] = v

        table = Table(title="Agent Configuration")
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green")

        for key, value in sorted(config.items()):
            # Mask sensitive values
            if (
                key.lower()
                in (
                    "anthropic_api_key",
                    "github_token",
                    "brave_search_api_key",
                    "password",
                    "secret",
                )
                or "api_key" in key.lower()
                or "token" in key.lower()
            ):
                value = "********"
            table.add_row(key, value)

        console.print(table)
    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr if e.stderr else str(e)}[/red]")


@piku.command(name="set")
@click.argument("key_value_pairs", nargs=-1)
def set_config(key_value_pairs):
    """Set configuration values for the agent environment.

    Example: silica piku set ANTHROPIC_API_KEY=abc123 DEBUG=true
    """
    if not key_value_pairs:
        console.print("[yellow]No key-value pairs provided[/yellow]")
        return

    try:
        workspace = get_workspace_name()
        app_name = get_app_name()

        # Build command with all valid key-value pairs
        config_args = []
        for pair in key_value_pairs:
            if "=" not in pair:
                console.print(
                    f"[yellow]Skipping invalid format: {pair}. Use KEY=VALUE format.[/yellow]"
                )
                continue

            key, value = pair.split("=", 1)
            # Mask sensitive values for display
            masked = (
                key.lower()
                in (
                    "anthropic_api_key",
                    "github_token",
                    "brave_search_api_key",
                    "password",
                    "secret",
                )
                or "api_key" in key.lower()
                or "token" in key.lower()
            )
            display_value = "********" if masked else value
            console.print(f"Setting {key}={display_value}")
            config_args.append(pair)

        if config_args:
            config_cmd = f"config:set {app_name} {' '.join(config_args)}"
            piku_utils.run_piku_in_silica(config_cmd, workspace_name=workspace)
            console.print("[green]Configuration updated successfully[/green]")
    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr if e.stderr else str(e)}[/red]")


@piku.command(name="shell")
@click.argument("command", required=False)
def shell(command):
    """Run a command in the agent environment shell.

    If no command is provided, starts an interactive shell session.
    """
    try:
        workspace = get_workspace_name()

        if command:
            # Run a single command using run_piku_in_silica
            piku_utils.run_piku_in_silica(
                command, use_shell_pipe=True, workspace_name=workspace
            )
            console.print("[green]Command executed successfully[/green]")
        else:
            # Start an interactive shell with the correct connection
            console.print(
                f"[yellow]Starting interactive shell for connection '{workspace}'. Type 'exit' to quit.[/yellow]"
            )
            # Use the connection string with piku
            piku_cmd = f"piku -r {workspace} shell"
            piku_utils.run_in_silica_dir(piku_cmd)
    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e.stderr if e.stderr else str(e)}[/red]")


@piku.command(name="upload")
@click.argument("local_path", type=click.Path(exists=True))
@click.argument("remote_path", required=False)
def upload(local_path, remote_path):
    """Upload a local file to the workspace.

    LOCAL_PATH is the path to the file or directory on your local machine.
    REMOTE_PATH is the destination path on the workspace relative to the app folder.
    If REMOTE_PATH is not provided, the file will be uploaded to the same relative path.

    Example: silica piku upload ./data/config.json data/
    """
    try:
        workspace = get_workspace_name()
        app_name = get_app_name()

        # Get full paths
        local_path = Path(local_path).resolve()

        # If remote_path is not provided, use the local filename
        if not remote_path:
            remote_path = local_path.name

        console.print(
            f"Uploading [blue]{local_path}[/blue] to workspace [green]{workspace}[/green]:[yellow]{app_name}/{remote_path}[/yellow]"
        )

        # Use scp to upload the file
        server = f"{workspace}"
        remote_dest = f"{server}:~/.piku/apps/{app_name}/{remote_path}"

        # Run scp command
        subprocess.run(["scp", "-r", str(local_path), remote_dest], check=True)

        console.print("[green]Upload completed successfully[/green]")
    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: Command failed: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")


@piku.command(name="tmux")
@click.argument("tmux_args", nargs=-1, required=False)
def tmux(tmux_args):
    """Access or interact with the tmux session for the workspace.

    This command provides a wrapper around the piku tmux functionality,
    allowing you to interact with the remote tmux session where your
    agent is running.

    If no arguments are provided, it will attach to the default tmux session.
    You can also pass specific tmux commands and arguments.

    Examples:
        silica piku tmux              # Attach to the default session
        silica piku tmux ls           # List all tmux sessions
        silica piku tmux new -s name  # Create a new named session
    """
    try:
        workspace = get_workspace_name()

        # Build the tmux command
        tmux_cmd = "tmux"
        if tmux_args:
            tmux_cmd += " " + " ".join(tmux_args)

        # When no arguments are provided, default to attaching
        if not tmux_args:
            console.print(f"[yellow]Connecting to tmux session on {workspace}[/yellow]")
            console.print(
                "[yellow]Use Ctrl+B followed by D to detach from the session[/yellow]"
            )
        else:
            console.print(f"[yellow]Running: tmux {' '.join(tmux_args)}[/yellow]")

        # Run the tmux command using the piku connection
        piku_cmd = f"piku -r {workspace} {tmux_cmd}"
        subprocess.run(piku_cmd, shell=True)

    except ValueError as e:
        console.print(f"[red]Error: {str(e)}[/red]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: Command failed: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")
