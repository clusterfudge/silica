"""Create command for silica."""

import subprocess
import click
from pathlib import Path
from rich.console import Console
import git

from silica.config import load_config, find_git_root
from silica.utils import piku as piku_utils

console = Console()


# Get templates from files
def get_template_content(filename):
    """Get the content of a template file."""
    template_path = (
        Path(__file__).parent.parent.parent / "utils" / "templates" / filename
    )
    if template_path.exists():
        with open(template_path, "r") as f:
            return f.read()
    else:
        console.print(f"[yellow]Warning: Template file {filename} not found.[/yellow]")
        return ""


@click.command()
@click.option(
    "-w", "--workspace", help="Name for the workspace (default: agent)", default=None
)
@click.option(
    "-c", "--connection", help="Piku connection string (default: piku)", default=None
)
def create(workspace, connection):
    """Create a new agent environment workspace."""
    config = load_config()

    # Set workspace name
    if workspace is None:
        workspace = config.get("workspace_name", "agent")

    # Set connection string
    if connection is None:
        connection = config.get("piku_connection", "piku")

    # Find git root
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    # Create .silica directory
    silica_dir = git_root / ".silica"
    silica_dir.mkdir(exist_ok=True)

    # Initialize a git repository in .silica
    console.print(f"Initializing agent environment in {silica_dir}...")

    try:
        # Create the agent repository
        repo_path = silica_dir / "agent-repo"
        repo_path.mkdir(exist_ok=True)

        # Initialize git repo in agent-repo
        if not (repo_path / ".git").exists():
            subprocess.run(["git", "init"], cwd=repo_path, check=True)

        initial_files = [
            ".python-version",
            "Procfile",
            "pyproject.toml",
            "requirements.txt",
        ]

        # Create initial files
        for filename in initial_files:
            content = get_template_content(filename)
            with open(repo_path / filename, "w") as f:
                f.write(content)

        # Add and commit files
        repo = git.Repo(repo_path)
        for filename in initial_files:
            repo.git.add(filename)

        if repo.is_dirty():
            repo.git.commit("-m", "Initial silica agent environment")
            console.print("[green]Committed initial agent environment files.[/green]")

        # Get the repository name from the git root
        repo_name = git_root.name

        # The app name will be {workspace}-{repo_name}
        app_name = f"{workspace}-{repo_name}"

        # Check if the workspace remote exists
        remotes = [r.name for r in repo.remotes]

        if workspace not in remotes:
            # We assume piku is already set up and the remote can be added
            console.print(f"Adding {workspace} remote to the agent repository...")
            # The remote URL format is: {connection}:{app_name}
            remote_url = f"{connection}:{app_name}"
            repo.create_remote(workspace, remote_url)
            console.print(f"Remote URL: {remote_url}")

        # Determine the current branch (could be main or master)
        # First check if any branch exists
        if not repo.heads:
            # No branches yet, create one
            console.print("Creating initial branch...")
            initial_branch = "main"  # Use main as the default for new repos
            repo.git.checkout("-b", initial_branch)
        else:
            # Use the current active branch
            initial_branch = repo.active_branch.name

        # Push to the workspace remote
        console.print(f"Pushing to {workspace} remote using branch {initial_branch}...")
        repo.git.push(workspace, initial_branch)
        console.print("[green]Successfully pushed agent environment to piku.[/green]")

        # The application name is workspace-{repo_name}
        app_name = f"{workspace}-{repo_name}"

        # Create code directory in remote
        console.print("Setting up code directory in remote environment...")
        try:
            # Use run_piku_in_silica function with the piku connection
            piku_utils.run_piku_in_silica(
                "mkdir -p code", use_shell_pipe=True, workspace_name=workspace
            )
        except subprocess.CalledProcessError as e:
            console.print(
                f"[yellow]Warning: Could not create code directory: {e}[/yellow]"
            )
            console.print(
                "[yellow]Continuing anyway, as the directory might be created automatically.[/yellow]"
            )

        # Set up environment variables
        console.print("Setting up environment variables...")

        # Prepare configuration dictionary
        env_config = {}

        # Set up credentials if available
        anthropic_key = config.get("api_keys", {}).get("anthropic")
        if anthropic_key:
            env_config["ANTHROPIC_API_KEY"] = anthropic_key

        github_token = config.get("api_keys", {}).get("github")
        if github_token:
            env_config["GITHUB_TOKEN"] = github_token

        # Set all configuration values at once if we have any
        if env_config:
            # Convert dictionary to KEY=VALUE format for piku config:set command
            config_args = [f"{k}={v}" for k, v in env_config.items()]
            config_cmd = f"config:set {' '.join(config_args)}"
            piku_utils.run_piku_in_silica(config_cmd, workspace_name=workspace)

        # Create local config file with new naming
        local_config = {
            "workspace_name": workspace,
            "piku_connection": connection,
            "app_name": app_name,
            "branch": initial_branch,
        }

        import yaml

        with open(silica_dir / "config.yaml", "w") as f:
            yaml.dump(local_config, f, default_flow_style=False)

        console.print("[green bold]Agent workspace created successfully![/green bold]")
        console.print(f"Workspace name: [cyan]{workspace}[/cyan]")
        console.print(f"Piku connection: [cyan]{connection}[/cyan]")
        console.print(f"Application name: [cyan]{app_name}[/cyan]")
        console.print(f"Branch: [cyan]{initial_branch}[/cyan]")

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error creating agent environment: {e}[/red]")
    except git.GitCommandError as e:
        console.print(f"[red]Git error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
